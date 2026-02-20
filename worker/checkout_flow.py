"""
Checkout flow automation using HTML analysis JSON.

Selects variants, adds to cart, navigates to cart and checkout pages,
and captures artifacts (screenshots, HTML, visible_text) for each step.
"""

from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PWTimeout

from shared.config import get_config
from shared.logging import get_logger
from worker.artifacts import (
    save_features_json,
    save_html_gz,
    save_screenshot,
    save_visible_text,
)
from worker.crawl import (
    dismiss_popups,
    extract_features_json,
    normalize_whitespace,
    scroll_sequence,
    wait_for_page_ready,
)
from worker.crawl.navigation_retry import navigate_with_retry
from worker.html_analysis import analyze_product_html
from worker.repository import AuditRepository

logger = get_logger(__name__)


async def run_checkout_flow(
    page: Page,
    product_url: str,
    html_analysis_json: dict,
    session_id: UUID,
    viewport: str,
    domain: str,
    repository: AuditRepository,
) -> dict:
    """
    Run checkout flow: select variants, add to cart, navigate to cart/checkout.

    Returns dict with status for each step.
    """
    result = {
        "variant_selection": {"status": "not_started", "selected_groups": []},
        "add_to_cart": {"status": "not_started"},
        "cart_navigation": {"status": "not_started"},
        "checkout_navigation": {"status": "not_started"},
        "errors": [],
    }

    logger.info(
        "checkout_flow_proceeding",
        session_id=str(session_id),
        viewport=viewport,
        domain=domain,
    )

    try:
        nav_result = await navigate_with_retry(
            page,
            product_url,
            session_id=session_id,
            repository=repository,
            page_type="product",
            viewport=viewport,
            domain=domain,
        )
        if not nav_result.success:
            result["errors"].append(f"Product navigation failed: {nav_result.error_summary}")
            return result

        await wait_for_page_ready(page, soft_timeout=10000)
        await dismiss_popups(page)
        await scroll_sequence(page)
        await dismiss_popups(page)

        variant_groups = html_analysis_json.get("variant_groups", [])
        has_variants = html_analysis_json.get("has_variants", False)

        if has_variants and variant_groups:
            logger.info(
                "selecting_variants",
                count=len(variant_groups),
                session_id=str(session_id),
            )
            selected = await _select_variants(page, variant_groups, repository, session_id)
            result["variant_selection"]["status"] = "completed" if selected else "failed"
            result["variant_selection"]["selected_groups"] = (
                [g.get("name") for g in variant_groups] if selected else []
            )

            if selected:
                await wait_for_page_ready(page, soft_timeout=5000)
                await dismiss_popups(page)
                await scroll_sequence(page)
                await dismiss_popups(page)

        add_to_cart_config = html_analysis_json.get("add_to_cart", {})
        has_add_to_cart = add_to_cart_config.get("found", False) or bool(
            add_to_cart_config.get("selector")
        )
        if has_add_to_cart:
            await asyncio.sleep(2)

            max_add_attempts = 3
            added = False

            for attempt in range(1, max_add_attempts + 1):
                added = await _add_to_cart(
                    page, add_to_cart_config, repository, session_id, viewport, domain
                )
                if added:
                    break

                logger.warning(
                    "add_to_cart_retry",
                    attempt=attempt,
                    max_attempts=max_add_attempts,
                    session_id=str(session_id),
                    viewport=viewport,
                    domain=domain,
                )

                await asyncio.sleep(2)
                await dismiss_popups(page)
                await scroll_sequence(page)
                await dismiss_popups(page)

            result["add_to_cart"]["status"] = "completed" if added else "failed"

            if added:
                await asyncio.sleep(2)
                await wait_for_page_ready(page, soft_timeout=5000)
                await dismiss_popups(page)

                cart_navigated, cart_load_timings = await _navigate_to_cart(
                    page, product_url, session_id, viewport, domain, repository
                )
                result["cart_navigation"]["status"] = "completed" if cart_navigated else "failed"

                if cart_navigated:
                    await wait_for_page_ready(page, soft_timeout=10000)
                    await scroll_sequence(page)
                    await dismiss_popups(page)

                    await _capture_page_payloads(
                        page, "cart", session_id, viewport, domain, repository, cart_load_timings
                    )

                    checkout_navigated, checkout_load_timings = await _navigate_to_checkout(
                        page, product_url, session_id, viewport, domain, repository
                    )
                    result["checkout_navigation"]["status"] = (
                        "completed" if checkout_navigated else "failed"
                    )

                    if checkout_navigated:
                        await wait_for_page_ready(page, soft_timeout=10000)
                        await scroll_sequence(page)
                        await dismiss_popups(page)

                        await _capture_page_payloads(
                            page, "checkout", session_id, viewport, domain, repository, checkout_load_timings
                        )
        else:
            result["errors"].append("Add-to-cart button not found in analysis JSON")

    except Exception as e:
        logger.error(
            "checkout_flow_failed",
            error=str(e),
            error_type=type(e).__name__,
            session_id=str(session_id),
        )
        result["errors"].append(f"Checkout flow error: {str(e)}")

    return result


async def _select_variants(
    page: Page, variant_groups: list[dict], repository: AuditRepository, session_id: UUID
) -> bool:
    """Select variant options from groups."""
    for group in variant_groups:
        group_name = group.get("name") or group.get("group_name") or "Unknown"
        options = group.get("options", [])
        control_type = group.get("control_type", "unknown")
        required = group.get("required", False)

        if not options:
            logger.warning("no_options_for_group", group=group_name)
            continue

        logger.info("selecting_variant_group", group=group_name, control_type=control_type)

        selected = False
        attempted_count = 0
        skipped_count = 0

        for option in options:
            disabled_hint = option.get("disabled_hint")
            if disabled_hint is not None:
                skipped_count += 1
                logger.debug(
                    "variant_option_skipped_disabled_trying_next",
                    group=group_name,
                    label=option.get("label", "Unknown"),
                    disabled_hint=disabled_hint,
                    skipped_count=skipped_count,
                    session_id=str(session_id),
                )
                continue

            attempted_count += 1
            logger.debug(
                "variant_option_attempting",
                group=group_name,
                label=option.get("label", "Unknown"),
                attempt=attempted_count,
                total_options=len(options),
                session_id=str(session_id),
            )

            if await _select_variant_option(page, option, group_name, control_type):
                selected = True
                logger.info(
                    "variant_option_selected_success",
                    group=group_name,
                    label=option.get("label", "Unknown"),
                    skipped_before=skipped_count,
                    attempts=attempted_count,
                    session_id=str(session_id),
                )
                repository.create_log(
                    session_id=session_id,
                    level="info",
                    event_type="navigation",
                    message="Variant selected",
                    details={
                        "group": group_name,
                        "option": option.get("label", "Unknown"),
                        "skipped_count": skipped_count,
                        "attempts": attempted_count,
                    },
                )
                await asyncio.sleep(1)
                break
            else:
                logger.debug(
                    "variant_option_failed_trying_next",
                    group=group_name,
                    label=option.get("label", "Unknown"),
                    attempt=attempted_count,
                    session_id=str(session_id),
                )

        if required and not selected:
            logger.error("required_variant_not_selected", group=group_name)
            return False

    return True


async def _select_variant_option(
    page: Page, option: dict, group_name: str, control_type: str
) -> bool:
    """Select a single variant option with improved visibility handling."""
    selector_type = option.get("selector_type", "css")
    selector = option.get("selector", "")
    label = option.get("label", "Unknown")

    if not selector:
        return False

    try:
        if control_type == "select" or (selector_type == "xpath" and "/option" in selector):
            return await _select_option_element(page, selector, selector_type, label, group_name)

        if selector_type == "xpath":
            import re

            test_id_match = None
            if "data-testid='" in selector or 'data-testid="' in selector:
                testid_matches = re.findall(r"data-testid=['\"]([^'\"]+)['\"]", selector)
                if testid_matches:
                    test_id_match = testid_matches[-1]

            if test_id_match:
                try:
                    locator = page.get_by_test_id(test_id_match)
                    count = await locator.count()
                    if count > 0:
                        if not await _is_disabled(locator):
                            try:
                                if await locator.is_visible(timeout=3000):
                                    await locator.click(timeout=5000)
                                    logger.info(
                                        "variant_option_selected", group=group_name, label=label
                                    )
                                    return True
                            except Exception:
                                pass

                            try:
                                await locator.click(timeout=5000, force=True)
                                logger.info(
                                    "variant_option_selected", group=group_name, label=label
                                )
                                return True
                            except Exception:
                                try:
                                    await locator.evaluate("el => el.click()")
                                    logger.info(
                                        "variant_option_selected", group=group_name, label=label
                                    )
                                    return True
                                except Exception:
                                    pass
                except Exception:
                    pass

            locator = page.locator(f"xpath={selector}")
        else:
            if selector.startswith("[data-testid=") or selector.startswith("*[data-testid="):
                test_id = _extract_test_id(selector)
                if test_id:
                    locator = page.get_by_test_id(test_id)
                else:
                    locator = page.locator(selector)
            else:
                locator = page.locator(selector)

        count = await locator.count()
        if count == 0:
            return False

        if count > 1:
            visible_locators = []
            for i in range(min(count, 5)):
                try:
                    single_locator = locator.nth(i)
                    if await single_locator.is_visible(timeout=1000):
                        if not await _is_disabled(single_locator):
                            visible_locators.append(single_locator)
                except Exception:
                    continue

            if not visible_locators:
                return False

            locator = visible_locators[0]
        else:
            is_visible = False
            try:
                is_visible = await locator.is_visible(timeout=3000)
            except Exception:
                pass

            if not is_visible:
                try:
                    await locator.scroll_into_view_if_needed(timeout=2000)
                    await asyncio.sleep(0.3)
                except Exception:
                    pass

        if await _is_disabled(locator):
            logger.debug(
                "variant_option_skipped_disabled_check",
                group=group_name,
                label=label,
                selector=selector,
            )
            return False

        text = await locator.inner_text() if await locator.count() > 0 else ""
        text_lower = text.lower()
        if any(
            phrase in text_lower
            for phrase in [
                "sold out",
                "out of stock",
                "unavailable",
                "not available",
                "temporarily unavailable",
            ]
        ):
            logger.debug(
                "variant_option_skipped_text_indicator",
                group=group_name,
                label=label,
                text_snippet=text[:50],
            )
            return False

        is_visible_final = False
        try:
            is_visible_final = await locator.is_visible(timeout=2000)
        except Exception:
            pass

        if not is_visible_final:
            try:
                await locator.scroll_into_view_if_needed(timeout=2000)
                await asyncio.sleep(0.5)
            except Exception:
                pass

        try:
            if is_visible_final or await locator.is_visible(timeout=1000):
                await locator.click(timeout=5000)
                logger.info("variant_option_selected", group=group_name, label=label)
                return True
        except Exception:
            pass

        try:
            await locator.click(timeout=5000, force=True)
            logger.info("variant_option_selected", group=group_name, label=label)
            return True
        except Exception:
            try:
                await locator.evaluate("el => el.click()")
                logger.info("variant_option_selected", group=group_name, label=label)
                return True
            except Exception:
                return False

    except Exception as e:
        error_msg = str(e)
        if "strict mode violation" in error_msg.lower() or "timeout" in error_msg.lower():
            try:
                if selector_type == "xpath":
                    all_locators = await page.locator(f"xpath={selector}").all()
                else:
                    all_locators = await page.locator(selector).all()

                for loc in all_locators[:5]:
                    try:
                        await loc.scroll_into_view_if_needed(timeout=2000)
                        await asyncio.sleep(0.3)
                        if await loc.is_visible(timeout=2000) and not await _is_disabled(loc):
                            await loc.click(timeout=5000)
                            logger.info("variant_option_selected", group=group_name, label=label)
                            return True
                    except Exception:
                        try:
                            await loc.click(timeout=5000, force=True)
                            logger.info("variant_option_selected", group=group_name, label=label)
                            return True
                        except Exception:
                            try:
                                await loc.evaluate("el => el.click()")
                                logger.info(
                                    "variant_option_selected", group=group_name, label=label
                                )
                                return True
                            except Exception:
                                continue
            except Exception:
                pass

        logger.warning(
            "variant_selection_failed", group=group_name, label=label, error=str(e)[:200]
        )
        return False


async def _select_option_element(
    page: Page, selector: str, selector_type: str, label: str, group_name: str
) -> bool:
    """Select an option from a select element."""
    try:
        if selector_type == "xpath" and "/option" in selector:
            select_part = selector.split("/option")[0]
            option_part = selector.split("/option")[1] if "/option" in selector else ""

            select_locator = page.locator(f"xpath={select_part}")
            if await select_locator.count() == 0:
                return False

            if not await select_locator.is_visible(timeout=3000):
                return False

            test_id = _extract_test_id_from_xpath(option_part)
            value = _extract_value_from_xpath(option_part)

            if test_id:
                option_locator = select_locator.locator(f"option[data-testid='{test_id}']")
                if await option_locator.count() > 0:
                    option_value = await option_locator.get_attribute("value")
                    if option_value:
                        await select_locator.select_option(value=option_value)
                        return True
            elif value:
                await select_locator.select_option(value=value)
                return True
            else:
                await select_locator.select_option(label=label)
                return True
        else:
            select_locator = page.locator(selector)
            if await select_locator.count() > 0:
                await select_locator.select_option(label=label)
                return True

    except Exception as e:
        logger.warning("select_option_failed", group=group_name, error=str(e))
        return False

    return False


def _extract_test_id(selector: str) -> Optional[str]:
    """Extract data-testid from CSS selector."""
    if "data-testid='" in selector:
        return selector.split("data-testid='")[1].split("'")[0]
    elif 'data-testid="' in selector:
        return selector.split('data-testid="')[1].split('"')[0]
    return None


def _extract_test_id_from_xpath(xpath_part: str) -> Optional[str]:
    """Extract data-testid from XPath option part."""
    if "@data-testid='" in xpath_part:
        return xpath_part.split("@data-testid='")[1].split("'")[0]
    elif '@data-testid="' in xpath_part:
        return xpath_part.split('@data-testid="')[1].split('"')[0]
    return None


def _extract_value_from_xpath(xpath_part: str) -> Optional[str]:
    """Extract value from XPath option part."""
    if "@value='" in xpath_part:
        return xpath_part.split("@value='")[1].split("'")[0]
    elif '@value="' in xpath_part:
        return xpath_part.split('@value="')[1].split('"')[0]
    return None


async def _is_disabled(locator) -> bool:
    """Check if locator is disabled - universal detection including strikethrough."""
    try:
        disabled = await locator.get_attribute("disabled")
        if disabled is not None:
            return True
        aria_disabled = await locator.get_attribute("aria-disabled")
        if aria_disabled == "true":
            return True
        classes = await locator.get_attribute("class") or ""
        class_lower = classes.lower()

        disabled_keywords = [
            "disabled",
            "sold-out",
            "out-of-stock",
            "unavailable",
            "not-available",
            "oos",
            "outofstock",
            "stock-0",
            "inventory-0",
        ]

        non_disabled_keywords = ["will-restock", "back-in-stock", "restock"]

        has_disabled_keyword = any(keyword in class_lower for keyword in disabled_keywords)
        has_only_restock_keyword = (
            any(keyword in class_lower for keyword in non_disabled_keywords)
            and not has_disabled_keyword
        )

        if has_disabled_keyword:
            return True

        if has_only_restock_keyword:
            return False

        text = await locator.inner_text() if await locator.count() > 0 else ""
        text_lower = text.lower()
        if any(
            phrase in text_lower
            for phrase in [
                "sold out",
                "out of stock",
                "unavailable",
                "not available",
                "temporarily unavailable",
            ]
        ):
            return True

        has_strikethrough = await locator.evaluate("""
            (el) => {
                const style = window.getComputedStyle(el);
                if (style.textDecoration.includes('line-through')) return true;
                
                const parent = el.parentElement;
                if (parent) {
                    const parentStyle = window.getComputedStyle(parent);
                    if (parentStyle.textDecoration.includes('line-through')) return true;
                }
                
                if (el.closest('s, strike, del')) return true;
                
                const textContent = el.textContent || '';
                const hasStrikeTag = el.querySelector('s, strike, del');
                if (hasStrikeTag) return true;
                
                return false;
            }
        """)
        if has_strikethrough:
            return True

        return False
    except Exception:
        return False


async def _add_to_cart(
    page: Page,
    add_to_cart_config: dict,
    repository: AuditRepository,
    session_id: UUID,
    viewport: str = "desktop",
    domain: str = "",
) -> bool:
    """Click add-to-cart button with improved visibility handling and error detection."""
    selector_type = add_to_cart_config.get("selector_type", "css")
    selector = add_to_cart_config.get("selector", "")
    click_strategy = add_to_cart_config.get("click_strategy", "normal_click")

    if not selector:
        return False

    try:
        if selector_type == "xpath":
            test_id_match = None
            import re

            testid_pattern = r"@data-testid=['\"]([^'\"]+)['\"]"
            match = re.search(testid_pattern, selector)
            if match:
                test_id_match = match.group(1)

            if test_id_match:
                try:
                    locator = page.get_by_test_id(test_id_match)
                    if await locator.count() > 0:
                        logger.debug(
                            "add_to_cart_using_test_id",
                            test_id=test_id_match,
                            session_id=str(session_id),
                            viewport=viewport,
                            domain=domain,
                        )
                    else:
                        locator = page.locator(f"xpath={selector}")
                        logger.debug(
                            "add_to_cart_test_id_not_found_fallback_xpath",
                            test_id=test_id_match,
                            selector=selector,
                            session_id=str(session_id),
                        )
                except Exception as e:
                    logger.debug(
                        "add_to_cart_test_id_error_fallback_xpath",
                        test_id=test_id_match,
                        error=str(e),
                        session_id=str(session_id),
                    )
                    locator = page.locator(f"xpath={selector}")
            else:
                locator = page.locator(f"xpath={selector}")
        else:
            if selector.startswith("[data-testid=") or selector.startswith("*[data-testid="):
                test_id = _extract_test_id(selector)
                if test_id:
                    locator = page.get_by_test_id(test_id)
                else:
                    locator = page.locator(selector)
            else:
                locator = page.locator(selector)

        count = await locator.count()
        if count == 0:
            return False

        if count > 1:
            visible_locators = []
            for i in range(min(count, 5)):
                try:
                    single_locator = locator.nth(i)
                    if await single_locator.is_visible(timeout=2000):
                        visible_locators.append(single_locator)
                except Exception:
                    continue

            if not visible_locators:
                await asyncio.sleep(2)
                for i in range(min(count, 5)):
                    try:
                        single_locator = locator.nth(i)
                        await single_locator.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                        if await single_locator.is_visible(timeout=2000):
                            visible_locators.append(single_locator)
                            break
                    except Exception:
                        continue

            if not visible_locators:
                logger.warning(
                    "add_to_cart_no_visible_elements_after_scroll",
                    selector=selector,
                    count=count,
                    session_id=str(session_id),
                    viewport=viewport,
                    domain=domain,
                )
                return False

            locator = visible_locators[0]
        else:
            is_visible = False
            try:
                is_visible = await locator.is_visible(timeout=3000)
            except Exception:
                pass

            if not is_visible:
                try:
                    await locator.scroll_into_view_if_needed(timeout=5000)
                    await asyncio.sleep(1)
                    is_visible = await locator.is_visible(timeout=2000)
                except Exception:
                    pass

                if not is_visible:
                    exists = await locator.count() > 0
                    if not exists:
                        logger.warning(
                            "add_to_cart_element_not_visible_after_scroll",
                            selector=selector,
                            session_id=str(session_id),
                            viewport=viewport,
                            domain=domain,
                        )
                        return False

        if click_strategy == "scroll_into_view_then_click":
            try:
                await locator.scroll_into_view_if_needed(timeout=5000)
                await asyncio.sleep(0.5)
            except Exception:
                await asyncio.sleep(0.5)

        is_disabled_check = False
        try:
            is_disabled_check = await _is_disabled(locator)
        except Exception:
            pass

        if is_disabled_check:
            for attempt in range(5):
                await asyncio.sleep(1)
                try:
                    if not await _is_disabled(locator):
                        break
                except Exception:
                    pass
            else:
                if await _is_disabled(locator):
                    logger.warning(
                        "add_to_cart_button_disabled",
                        selector=selector,
                        session_id=str(session_id),
                        viewport=viewport,
                        domain=domain,
                    )
                    return False

        if not await locator.is_visible(timeout=3000):
            try:
                await locator.scroll_into_view_if_needed(timeout=3000)
                await asyncio.sleep(0.5)
            except Exception:
                pass

        clicked = False
        try:
            if click_strategy == "js_click":
                await locator.evaluate("el => el.click()")
                clicked = True
            elif click_strategy == "force_click":
                await locator.click(force=True, timeout=5000)
                clicked = True
            else:
                await locator.click(timeout=5000)
                clicked = True
        except Exception as e:
            logger.warning(
                "add_to_cart_primary_click_failed_trying_alternatives",
                selector=selector,
                click_strategy=click_strategy,
                error=str(e),
                error_type=type(e).__name__,
                session_id=str(session_id),
                viewport=viewport,
                domain=domain,
            )
            try:
                await locator.evaluate("el => el.click()")
                clicked = True
            except Exception:
                try:
                    await locator.click(force=True, timeout=5000)
                    clicked = True
                except Exception as e2:
                    logger.error(
                        "add_to_cart_all_click_methods_failed",
                        selector=selector,
                        error=str(e2),
                        error_type=type(e2).__name__,
                        session_id=str(session_id),
                        viewport=viewport,
                        domain=domain,
                    )
                    return False

        if clicked:
            await asyncio.sleep(2)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except PWTimeout:
                try:
                    await page.wait_for_load_state("load", timeout=5000)
                except PWTimeout:
                    await asyncio.sleep(2)

            error_selectors = [
                ".error",
                ".error-message",
                "[role='alert']",
                ".alert-error",
                ".notification--error",
            ]

            for error_sel in error_selectors:
                try:
                    error_elem = page.locator(error_sel).first
                    if await error_elem.is_visible(timeout=2000):
                        error_text = await error_elem.inner_text()
                        if error_text and any(
                            phrase in error_text.lower()
                            for phrase in [
                                "sorry, there was an issue",
                                "issue adding this item",
                                "please try again",
                                "unable to add",
                                "failed to add",
                            ]
                        ):
                            logger.error(f"Add-to-cart error detected: {error_text[:200]}")
                            return False
                except Exception:
                    continue

            logger.info(
                "add_to_cart_clicked",
                session_id=str(session_id),
                viewport=viewport,
                domain=domain,
                click_strategy=click_strategy,
                selector_type=selector_type,
            )
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="navigation",
                message="Add to cart clicked",
                details={
                    "strategy": click_strategy,
                    "viewport": viewport,
                    "domain": domain,
                    "selector_type": selector_type,
                },
            )
            config = get_config()
            if config.telegram_bot_token and config.telegram_chat_id:
                try:
                    from shared.telegram import send_telegram_message

                    msg = (
                        "🛒 Checkout: Add to cart clicked\n"
                        f"domain: {domain}\n"
                        f"viewport: {viewport}\n"
                        f"session_id: {session_id}\n"
                        f"strategy: {click_strategy}"
                    )
                    if send_telegram_message(
                        bot_token=config.telegram_bot_token,
                        chat_id=config.telegram_chat_id,
                        message=msg,
                    ):
                        logger.info(
                            "telegram_checkout_add_to_cart_sent",
                            session_id=str(session_id),
                            viewport=viewport,
                            domain=domain,
                        )
                    else:
                        logger.warning(
                            "telegram_checkout_add_to_cart_failed",
                            session_id=str(session_id),
                        )
                except Exception as e:
                    logger.warning(
                        "telegram_checkout_add_to_cart_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        session_id=str(session_id),
                    )
            return True

    except Exception as e:
        logger.error("add_to_cart_failed", error=str(e), session_id=str(session_id))
        return False


async def _navigate_to_cart(
    page: Page,
    base_url: str,
    session_id: UUID,
    viewport: str,
    domain: str,
    repository: AuditRepository,
) -> bool:
    """Navigate to cart page."""
    cart_selectors = [
        'a[href*="/cart"]',
        'a[href*="/basket"]',
        'a[href*="/bag"]',
        '[data-testid*="cart"]',
        '[aria-label*="cart" i]',
    ]

    for selector in cart_selectors:
        try:
            elements = await page.locator(selector).all()
            for elem in elements[:5]:
                if not await elem.is_visible():
                    continue

                href = await elem.get_attribute("href")
                if href:
                    parsed_href = urlparse(href)
                    if parsed_href.netloc and parsed_href.netloc != urlparse(base_url).netloc:
                        continue

                await elem.click(timeout=3000)
                await asyncio.sleep(2)
                load_timings = await wait_for_page_ready(page, soft_timeout=5000)

                current_url = page.url.lower()
                if "cart" in current_url or "basket" in current_url:
                    return True, load_timings
        except Exception:
            continue

    cart_paths = ["/cart", "/basket", "/bag"]
    for path in cart_paths:
        try:
            cart_url = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}{path}"
            nav_result = await navigate_with_retry(
                page,
                cart_url,
                session_id=session_id,
                repository=repository,
                page_type="cart",
                viewport=viewport,
                domain=domain,
            )
            if nav_result.success:
                load_timings = await wait_for_page_ready(page, soft_timeout=5000)
                return True, load_timings
        except Exception:
            continue

    return False, {}


async def _navigate_to_checkout(
    page: Page,
    base_url: str,
    session_id: UUID,
    viewport: str,
    domain: str,
    repository: AuditRepository,
) -> bool:
    """Navigate to checkout page."""
    checkout_selectors = [
        'button:has-text("checkout securely" i)',
        'button:has-text("checkout securely")',
        'button:has-text("CHECKOUT SECURELY")',
        'button:has-text("proceed to checkout" i)',
        'button:has-text("proceed to checkout")',
        'button:has-text("secure checkout" i)',
        'button:has-text("secure checkout")',
        'button:has-text("checkout" i)',
        'a:has-text("checkout securely" i)',
        'a:has-text("checkout" i)',
        'a[href*="/checkout"]',
        '[data-testid*="checkout"]',
        '[aria-label*="checkout" i]',
    ]

    for selector in checkout_selectors:
        try:
            elements = await page.locator(selector).all()
            for elem in elements[:5]:
                if not await elem.is_visible():
                    continue

                href = await elem.get_attribute("href")
                if href:
                    parsed_href = urlparse(href)
                    if parsed_href.netloc and parsed_href.netloc != urlparse(base_url).netloc:
                        continue

                button_text = await elem.inner_text() if await elem.count() > 0 else ""
                logger.debug(
                    "checkout_button_found",
                    selector=selector,
                    text=button_text[:50],
                    session_id=str(session_id),
                    viewport=viewport,
                    domain=domain,
                )

                await elem.click(timeout=5000)
                await asyncio.sleep(2)
                load_timings = await wait_for_page_ready(page, soft_timeout=5000)

                current_url = page.url.lower()
                if "checkout" in current_url:
                    logger.info(
                        "checkout_navigation_success",
                        selector=selector,
                        url=current_url,
                        session_id=str(session_id),
                        viewport=viewport,
                        domain=domain,
                    )
                    return True, load_timings
        except Exception as e:
            logger.debug(
                "checkout_selector_failed",
                selector=selector,
                error=str(e)[:100],
                session_id=str(session_id),
            )
            continue

    try:
        checkout_url = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}/checkout"
        nav_result = await navigate_with_retry(
            page,
            checkout_url,
            session_id=session_id,
            repository=repository,
            page_type="checkout",
            viewport=viewport,
            domain=domain,
        )
        if nav_result.success:
            load_timings = await wait_for_page_ready(page, soft_timeout=5000)
            return True, load_timings
    except Exception:
        pass

    return False, {}


async def _capture_page_payloads(
    page: Page,
    page_type: str,
    session_id: UUID,
    viewport: str,
    domain: str,
    repository: AuditRepository,
    load_timings: Optional[dict] = None,
) -> None:
    """Capture artifacts for a page."""
    try:
        page_data = repository.get_page_by_session_type_viewport(session_id, page_type, viewport)
        if not page_data:
            page_data = repository.create_page(
                session_id=session_id,
                page_type=page_type,
                viewport=viewport,
                status="pending",
            )
        page_id = page_data["id"]

        visible_text = await page.inner_text("body")
        visible_text = normalize_whitespace(visible_text)

        try:
            screenshot_bytes = await page.screenshot(type="png", full_page=True)
        except Exception:
            screenshot_bytes = None

        features = await extract_features_json(page)

        save_screenshot(
            repository,
            session_id,
            page_id,
            page_type,
            viewport,
            domain,
            screenshot_bytes,
        )
        save_visible_text(
            repository,
            session_id,
            page_id,
            page_type,
            viewport,
            domain,
            visible_text,
        )
        save_features_json(
            repository,
            session_id,
            page_id,
            page_type,
            viewport,
            domain,
            features,
        )

        html_content = await page.content()
        save_html_gz(
            repository,
            session_id,
            page_id,
            page_type,
            viewport,
            domain,
            html_content,
        )

        if page_type == "cart" and html_content:
            analyze_product_html(
                None,
                session_id,
                page_id,
                page_type,
                viewport,
                domain,
                repository,
            )

        repository.update_page(page_id, status="ok", load_timings=load_timings or {})

    except Exception as e:
        logger.error(
            "payload_capture_failed",
            page_type=page_type,
            error=str(e),
            error_type=type(e).__name__,
        )
