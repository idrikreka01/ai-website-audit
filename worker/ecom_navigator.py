"""
Universal ecommerce page navigator: product discovery, cart, checkout navigation.

Discovers product pages from homepage, handles variants, adds to cart,
navigates to cart and checkout, captures payloads using existing artifact methods.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

from playwright.async_api import Browser, Page, async_playwright

from shared.config import get_config
from shared.logging import bind_request_context, get_logger
from worker.artifacts import (
    save_features_json,
    save_html_gz,
    save_screenshot,
    save_visible_text,
)
from worker.checkout_flow import run_checkout_flow
from worker.crawl import (
    CONSENT_POSITIONING_DELAY_MS,
    DEFAULT_VENDORS,
    add_preconsent_init_scripts,
    apply_preconsent_in_frames,
    create_browser_context,
    dismiss_popups,
    extract_features_json,
    extract_features_json_pdp,
    normalize_whitespace,
    scroll_sequence,
    wait_for_page_ready,
)
from worker.crawl.navigation_retry import navigate_with_retry
from worker.crawl.pdp_candidates import (
    extract_pdp_candidate_links,
    normalize_internal_url,
)
from worker.crawl.pdp_validation import PRICE_PATTERN, extract_pdp_validation_signals
from worker.html_analysis import analyze_product_html
from worker.repository import AuditRepository

logger = get_logger(__name__)


@dataclass
class NavigationResult:
    """Result of ecommerce navigation."""

    product_url: Optional[str] = None
    cart_url: Optional[str] = None
    cart_state_type: str = "not_found"
    checkout_url: Optional[str] = None
    product_status: str = "not_found"
    cart_status: str = "not_found"
    checkout_status: str = "not_found"
    product_page_id: Optional[UUID] = None
    cart_page_id: Optional[UUID] = None
    checkout_page_id: Optional[UUID] = None
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class UniversalEcomNavigator:
    """Universal ecommerce page navigator."""

    def __init__(
        self,
        base_url: str,
        session_id: UUID,
        repository: AuditRepository,
        viewport: str = "desktop",
        headless: Optional[bool] = None,
    ):
        self.base_url = base_url
        self.session_id = session_id
        self.repository = repository
        self.viewport = viewport
        if headless is None:
            config = get_config()
            self.headless = config.browser_headless
        else:
            self.headless = headless
        self.domain = urlparse(base_url).netloc or ""
        self.result = NavigationResult()

    async def navigate(self) -> NavigationResult:
        """Main navigation flow: product → cart → checkout."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            try:
                await self._find_and_capture_product(browser)
                if self.result.product_url:
                    await self._add_to_cart_and_navigate(browser)
                    if self.result.cart_url:
                        await self._navigate_to_checkout(browser)
            finally:
                await browser.close()
        return self.result

    async def _find_and_capture_product(self, browser: Browser) -> None:
        """Find product page using fallback chain and capture payloads."""
        bind_request_context(
            session_id=str(self.session_id),
            page_type="product",
            viewport=self.viewport,
            domain=self.domain,
        )

        context = await create_browser_context(browser, self.viewport)
        page = None
        try:
            try:
                vendors = await add_preconsent_init_scripts(context, DEFAULT_VENDORS)
                self.repository.create_log(
                    session_id=self.session_id,
                    level="info",
                    event_type="navigation",
                    message="Preconsent init scripts added",
                    details={"vendors": vendors, "phase": "init"},
                )
            except Exception as e:
                logger.warning("preconsent_init_failed", error=str(e))

            page = await context.new_page()

            nav_result = await navigate_with_retry(
                page,
                self.base_url,
                session_id=self.session_id,
                repository=self.repository,
                page_type="homepage",
                viewport=self.viewport,
                domain=self.domain,
            )
            if not nav_result.success:
                self.result.errors.append(f"Homepage navigation failed: {nav_result.error_summary}")
                self.result.product_status = "failed"
                return

            await apply_preconsent_in_frames(page, DEFAULT_VENDORS)
            await wait_for_page_ready(page, soft_timeout=10000)
            await asyncio.sleep(CONSENT_POSITIONING_DELAY_MS / 1000)
            await dismiss_popups(page)
            await scroll_sequence(page)
            await dismiss_popups(page)

            product_url = await self._discover_product_url(page)
            if not product_url:
                self.result.product_status = "not_found"
                self.result.errors.append("Product page not found")
                return

            nav_result = await navigate_with_retry(
                page,
                product_url,
                session_id=self.session_id,
                repository=self.repository,
                page_type="product",
                viewport=self.viewport,
                domain=self.domain,
            )
            if not nav_result.success:
                self.result.errors.append(f"Product navigation failed: {nav_result.error_summary}")
                self.result.product_status = "failed"
                return

            await apply_preconsent_in_frames(page, DEFAULT_VENDORS)
            await wait_for_page_ready(page, soft_timeout=10000)
            await asyncio.sleep(CONSENT_POSITIONING_DELAY_MS / 1000)
            await dismiss_popups(page)
            await scroll_sequence(page)
            await dismiss_popups(page)

            if not await self._validate_product_page(page):
                self.result.errors.append("Product page validation failed")
                self.result.product_status = "invalid"
                return

            await self._handle_variants(page)
            await self._capture_page_payloads(page, "product")
            self.result.product_url = product_url
            self.result.product_status = "found"

            html_analysis_json = await self._get_html_analysis_json()
            if html_analysis_json:
                await self._run_checkout_flow_with_json(page, html_analysis_json)

        except Exception as e:
            logger.error("product_discovery_failed", error=str(e), error_type=type(e).__name__)
            self.result.errors.append(f"Product discovery error: {str(e)}")
            self.result.product_status = "failed"
        finally:
            if page:
                await page.close()
            if context:
                await context.close()

    async def _discover_product_url(self, page: Page) -> Optional[str]:
        """Discover product URL using fallback chain."""
        logger.info("product_discovery_started", base_url=self.base_url)

        method_a = await self._scan_homepage_for_product_links(page)
        if method_a:
            logger.info("product_found_method_a", url=method_a)
            self.repository.create_log(
                session_id=self.session_id,
                level="info",
                event_type="navigation",
                message="Product found via homepage scan",
                details={"method": "homepage_scan", "url": method_a},
            )
            return method_a

        method_b = await self._click_shop_entry_points(page)
        if method_b:
            logger.info("product_found_method_b", url=method_b)
            self.repository.create_log(
                session_id=self.session_id,
                level="info",
                event_type="navigation",
                message="Product found via shop entry",
                details={"method": "shop_entry", "url": method_b},
            )
            return method_b

        method_c = await self._use_site_search(page)
        if method_c:
            logger.info("product_found_method_c", url=method_c)
            self.repository.create_log(
                session_id=self.session_id,
                level="info",
                event_type="navigation",
                message="Product found via site search",
                details={"method": "site_search", "url": method_c},
            )
            return method_c

        method_d = await self._crawl_internal_links(page)
        if method_d:
            logger.info("product_found_method_d", url=method_d)
            self.repository.create_log(
                session_id=self.session_id,
                level="info",
                event_type="navigation",
                message="Product found via internal crawl",
                details={"method": "internal_crawl", "url": method_d},
            )
            return method_d

        return None

    async def _scan_homepage_for_product_links(self, page: Page) -> Optional[str]:
        """Method A: Scan homepage for product-like links."""
        try:
            candidates = await extract_pdp_candidate_links(page, self.base_url, max_candidates=10)
            for candidate_url in candidates:
                if await self._validate_candidate_url(page, candidate_url):
                    return candidate_url
        except Exception as e:
            logger.warning("homepage_scan_failed", error=str(e))
        return None

    async def _validate_candidate_url(self, page: Page, url: str) -> bool:
        """Quick validation: check if URL looks like a product page (not listing/category)."""
        parsed = urlparse(url)
        path = (parsed.path or "/").lower()

        listing_indicators = [
            "/pl",
            "/list",
            "/category",
            "/categories",
            "/search",
            "/browse",
            "/shop",
        ]
        if any(indicator in path for indicator in listing_indicators):
            return False

        if path.count("/") > 4:
            return False

        return True

    async def _click_shop_entry_points(self, page: Page) -> Optional[str]:
        """Method B: Click likely shop entry points."""
        shop_selectors = [
            'a:has-text("Shop")',
            'a:has-text("Catalog")',
            'a:has-text("All Products")',
            'a:has-text("Store")',
            'a:has-text("New")',
            'a:has-text("Best Sellers")',
            '[href*="/shop"]',
            '[href*="/catalog"]',
            '[href*="/products"]',
        ]
        for selector in shop_selectors:
            try:
                elements = await page.locator(selector).all()
                for elem in elements[:3]:
                    if await elem.is_visible():
                        href = await elem.get_attribute("href")
                        if href:
                            url = normalize_internal_url(href, self.base_url)
                            if url:
                                await elem.click()
                                await wait_for_page_ready(page, soft_timeout=5000)
                                await scroll_sequence(page)
                                candidates = await extract_pdp_candidate_links(
                                    page, self.base_url, max_candidates=1
                                )
                                if candidates:
                                    return candidates[0]
            except Exception:
                continue
        return None

    async def _use_site_search(self, page: Page) -> Optional[str]:
        """Method C: Use site search if present."""
        search_selectors = [
            'input[type="search"]',
            'input[name*="search"]',
            '[class*="search"] input',
            '[id*="search"] input',
            'button[aria-label*="search" i]',
        ]
        for selector in search_selectors:
            try:
                search_input = page.locator(selector).first
                if await search_input.is_visible():
                    await search_input.fill("a")
                    await search_input.press("Enter")
                    await wait_for_page_ready(page, soft_timeout=5000)
                    await scroll_sequence(page)
                    candidates = await extract_pdp_candidate_links(
                        page, self.base_url, max_candidates=1
                    )
                    if candidates:
                        return candidates[0]
            except Exception:
                continue
        return None

    async def _crawl_internal_links(self, page: Page) -> Optional[str]:
        """Method D: Crawl limited internal links and select best candidate."""
        try:
            links = await page.locator("a[href]").all()
            seen = set()
            candidates = []
            for link in links[:40]:
                href = await link.get_attribute("href")
                if not href:
                    continue
                url = normalize_internal_url(href, self.base_url)
                if not url or url in seen:
                    continue
                seen.add(url)
                parsed = urlparse(url)
                path = (parsed.path or "/").lower()
                if any(excluded in path for excluded in ["account", "cart", "checkout", "login"]):
                    continue
                candidates.append(url)
                if len(candidates) >= 10:
                    break

            for candidate_url in candidates:
                try:
                    nav_result = await navigate_with_retry(
                        page,
                        candidate_url,
                        session_id=self.session_id,
                        repository=self.repository,
                        page_type="product",
                        viewport=self.viewport,
                        domain=self.domain,
                    )
                    if nav_result.success:
                        await wait_for_page_ready(page, soft_timeout=5000)
                        signals = await extract_pdp_validation_signals(page)
                        if signals.get("has_price") and signals.get("has_add_to_cart"):
                            body_text = await page.inner_text("body")
                            has_h1 = await page.locator("h1").first.count() > 0
                            if has_h1 and PRICE_PATTERN.search(body_text):
                                return candidate_url
                except Exception:
                    continue
        except Exception as e:
            logger.warning("internal_crawl_failed", error=str(e))
        return None

    async def _validate_product_page(self, page: Page) -> bool:
        """Validate product page using heuristics."""
        signals = await extract_pdp_validation_signals(page)
        has_h1 = await page.locator("h1").first.count() > 0
        body_text = await page.inner_text("body")
        has_price = bool(PRICE_PATTERN.search(body_text))
        has_add_to_cart = signals.get("has_add_to_cart", False)

        return has_h1 and has_price and has_add_to_cart

    async def _handle_variants(self, page: Page) -> None:
        """Dispatch to platform-specific variant handlers."""
        platform, signals = await self._detect_platform(page)
        logger.info("variant_platform_detected", platform=platform, signals=signals)
        self.repository.create_log(
            session_id=self.session_id,
            level="info",
            event_type="navigation",
            message="Variant platform detected",
            details={"platform": platform, "signals": signals},
        )

        try:
            if platform == "shopify":
                await self._handle_variants_shopify(page)
            elif platform == "woocommerce":
                await self._handle_variants_woocommerce(page)
            else:
                await self._handle_variants_generic(page)
        except Exception as e:
            logger.warning("variant_platform_handling_failed", error=str(e), platform=platform)

    async def _detect_platform(self, page: Page) -> tuple[str, list[str]]:
        """Detect ecommerce platform from DOM, scripts, and URL."""
        signals: list[str] = []
        try:
            html = await page.content()
        except Exception:
            html = ""

        url_lower = (page.url or "").lower()

        shopify_indicators = [
            'form[action*="/cart/add"]',
            "[data-product-id]",
            "[data-product-handle]",
            "[id*='shopify-section']",
            "[class*='shopify-section']",
            "script[src*='cdn.shopify.com']",
        ]
        woocommerce_indicators = [
            "form.variations_form",
            "[class*='woocommerce']",
            "script[src*='woocommerce']",
            "script[src*='wc-ajax']",
            'select[name^="attribute_"]',
            ".single_add_to_cart_button",
        ]

        for selector in shopify_indicators:
            try:
                count = await page.locator(selector).count()
                if count > 0:
                    signals.append(f"dom:{selector}")
            except Exception:
                continue

        for selector in woocommerce_indicators:
            try:
                count = await page.locator(selector).count()
                if count > 0:
                    signals.append(f"dom:{selector}")
            except Exception:
                continue

        if "cdn.shopify.com" in html:
            signals.append("html:cdn.shopify.com")
        if "Shopify.theme" in html or "window.Shopify" in html:
            signals.append("html:shopify-global")

        if "woocommerce" in html.lower() or "wc_add_to_cart_params" in html:
            signals.append("html:woocommerce")
        if "wc-ajax" in html.lower():
            signals.append("html:wc-ajax")

        parsed = urlparse(url_lower)
        if "myshopify.com" in parsed.netloc:
            signals.append("url:myshopify.com")

        platform = "generic"
        if any("shopify" in s for s in signals):
            platform = "shopify"
        elif any("woocommerce" in s or "wc-ajax" in s for s in signals):
            platform = "woocommerce"

        return platform, signals

    async def _stabilize_pdp_before_atc(self, page: Page) -> None:
        """Stabilize PDP before attempting add-to-cart."""
        await wait_for_page_ready(page, soft_timeout=10000)
        await dismiss_popups(page)
        await scroll_sequence(page)
        await dismiss_popups(page)
        await asyncio.sleep(0.5)

    async def _ensure_product_is_purchasable(self, page: Page, platform: str) -> bool:
        """Best-effort check that product is purchasable.

        Focus on purchase UI region instead of entire body.
        """
        sold_out_keywords = ["sold out", "out of stock", "unavailable"]

        if platform == "shopify":
            container = page.locator('form[action*="/cart/add"]').first
        elif platform == "woocommerce":
            container = page.locator("form.variations_form, form.cart").first
        else:
            container = page.locator(
                'form[action*="/cart"], form[action*="/basket"], [class*="product"]'
            ).first

        try:
            if await container.count() > 0:
                region_text = (await container.inner_text()).lower()
                if any(k in region_text for k in sold_out_keywords):
                    logger.info("product_not_purchasable_text_signal", platform=platform)
                    return False
        except Exception:
            pass

        disabled_cta_selectors = [
            'button[disabled][type="submit"]',
            'button[aria-disabled="true"]',
            ".is-disabled",
            ".disabled",
        ]
        for selector in disabled_cta_selectors:
            try:
                scoped = container.locator(selector) if container else page.locator(selector)
                locator = scoped.first
                if await locator.is_visible():
                    logger.info(
                        "product_not_purchasable_disabled_cta",
                        selector=selector,
                        platform=platform,
                    )
                    return False
            except Exception:
                continue

        try:
            if platform == "shopify":
                form = page.locator('form[action*="/cart/add"]').first
                hidden_variant_input = form.locator('input[name="id"]')
                if await hidden_variant_input.count() > 0:
                    value = await hidden_variant_input.first.get_attribute("value")
                    if not value or value == "0":
                        logger.info("product_not_purchasable_missing_variant_id", platform=platform)
                        return False
            elif platform == "woocommerce":
                form = page.locator("form.variations_form").first
                variation_id_input = form.locator('input[name="variation_id"]')
                if await variation_id_input.count() > 0:
                    value = await variation_id_input.first.get_attribute("value")
                    if not value or value == "0":
                        logger.info(
                            "product_not_purchasable_missing_variation_id",
                            platform=platform,
                        )
                        return False
        except Exception:
            pass

        return True

    async def _handle_variants_shopify(self, page: Page) -> None:
        """Shopify-specific variant resolution."""
        try:
            form = page.locator('form[action*="/cart/add"]').first
            if await form.count() == 0:
                await self._handle_variants_generic(page)
                return

            selects = await form.locator("select").all()
            for select in selects:
                try:
                    if not await select.is_visible():
                        continue
                    options = await select.locator(
                        "option:not([disabled]):not([value='']):not([value='0'])"
                    ).all()
                    if len(options) > 1:
                        await select.select_option(index=1)
                        await asyncio.sleep(0.5)
                except Exception:
                    continue

            radios = await form.locator('input[type="radio"]:not([disabled])').all()
            if radios:
                grouped: dict[str, list] = {}
                for radio in radios:
                    try:
                        if not await radio.is_visible():
                            continue
                        name = await radio.get_attribute("name")
                        if not name:
                            continue
                        grouped.setdefault(name, []).append(radio)
                    except Exception:
                        continue
                for group in grouped.values():
                    try:
                        await group[0].click(timeout=3000)
                        await asyncio.sleep(0.5)
                    except Exception:
                        continue

            hidden_variant_input = form.locator('input[name="id"]')
            try:
                if await hidden_variant_input.count() > 0:
                    _ = await hidden_variant_input.first.get_attribute("value")
            except Exception:
                pass

        except Exception as e:
            logger.warning("shopify_variant_handling_failed", error=str(e))
            await self._handle_variants_generic(page)

    async def _handle_variants_woocommerce(self, page: Page) -> None:
        """WooCommerce-specific variant resolution."""
        try:
            form = page.locator("form.variations_form").first
            if await form.count() == 0:
                await self._handle_variants_generic(page)
                return

            attribute_selects = await form.locator('select[name^="attribute_"]').all()
            for select in attribute_selects:
                try:
                    if not await select.is_visible():
                        continue
                    options = await select.locator("option:not([disabled]):not([value=''])").all()
                    if len(options) > 1:
                        await select.select_option(index=1)
                        await asyncio.sleep(0.7)
                except Exception:
                    continue

            variation_id_input = form.locator('input[name="variation_id"]')
            add_to_cart_button = form.locator(".single_add_to_cart_button").first

            try:
                if await variation_id_input.count() > 0 or await add_to_cart_button.count() > 0:
                    for _ in range(6):
                        resolved = False
                        if await variation_id_input.count() > 0:
                            value = await variation_id_input.first.get_attribute("value")
                            if value and value != "0":
                                resolved = True
                        if not resolved and await add_to_cart_button.count() > 0:
                            try:
                                if await add_to_cart_button.is_enabled():
                                    resolved = True
                            except Exception:
                                pass
                        if resolved:
                            break
                        await asyncio.sleep(0.5)
            except Exception:
                pass

        except Exception as e:
            logger.warning("woocommerce_variant_handling_failed", error=str(e))
            await self._handle_variants_generic(page)

    async def _handle_variants_generic(self, page: Page) -> None:
        """Handle product variants: selects, radios, swatches.

        Only interact with visible elements.
        """
        try:
            selects = await page.locator("select").all()
            for select in selects:
                try:
                    if not await select.is_visible():
                        continue
                    options = await select.locator("option:not([disabled])").all()
                    if len(options) > 1:
                        await select.select_option(index=1)
                        await asyncio.sleep(0.5)
                except Exception:
                    continue

            radios = await page.locator('input[type="radio"]:not([disabled])').all()
            if radios:
                grouped: dict[str, list] = {}
                for radio in radios:
                    try:
                        if not await radio.is_visible():
                            continue
                        aria_hidden = await radio.get_attribute("aria-hidden")
                        if aria_hidden == "true":
                            continue
                        name = await radio.get_attribute("name")
                        if name:
                            if name not in grouped:
                                grouped[name] = []
                            grouped[name].append(radio)
                    except Exception:
                        continue
                for name, group in grouped.items():
                    if len(group) > 1:
                        try:
                            await group[0].click(timeout=3000)
                            await asyncio.sleep(0.5)
                        except Exception:
                            pass

            swatches = await page.locator(
                '[class*="swatch"], [class*="variant"], [data-variant]'
            ).all()
            if swatches:
                for swatch in swatches[:3]:
                    try:
                        if await swatch.is_visible() and await swatch.is_enabled():
                            await swatch.click()
                            await asyncio.sleep(0.5)
                            break
                    except Exception:
                        continue

            subscription_toggles = await page.locator(
                'input[type="checkbox"][name*="subscription" i], '
                'input[type="radio"][value*="one-time" i]'
            ).all()
            for toggle in subscription_toggles:
                try:
                    if not await toggle.is_visible():
                        continue
                    value = await toggle.get_attribute("value")
                    if value and "one-time" in value.lower():
                        await toggle.click()
                        await asyncio.sleep(0.5)
                        break
                except Exception:
                    continue

            quantity_inputs = await page.locator(
                'input[name*="quantity" i], input[type="number"]'
            ).all()
            for qty_input in quantity_inputs[:1]:
                try:
                    if await qty_input.is_visible():
                        await qty_input.fill("1")
                        await asyncio.sleep(0.3)
                except Exception:
                    continue

        except Exception as e:
            logger.warning("variant_handling_failed", error=str(e))

    async def _add_to_cart_and_navigate(self, browser: Browser) -> None:
        """Add product to cart and navigate to cart page."""
        bind_request_context(
            session_id=str(self.session_id),
            page_type="cart",
            viewport=self.viewport,
            domain=self.domain,
        )

        context = await create_browser_context(browser, self.viewport)
        page = None
        try:
            page = await context.new_page()

            nav_result = await navigate_with_retry(
                page,
                self.result.product_url,
                session_id=self.session_id,
                repository=self.repository,
                page_type="product",
                viewport=self.viewport,
                domain=self.domain,
            )
            if not nav_result.success:
                self.result.errors.append("Failed to navigate to product for cart")
                self.result.cart_status = "failed"
                return

            await self._stabilize_pdp_before_atc(page)

            platform, signals = await self._detect_platform(page)
            logger.info("add_to_cart_platform_detected", platform=platform, signals=signals)
            self.repository.create_log(
                session_id=self.session_id,
                level="info",
                event_type="navigation",
                message="Add to cart platform detected",
                details={"platform": platform, "signals": signals},
            )

            if not await self._ensure_product_is_purchasable(page, platform):
                self.result.errors.append("Product appears not purchasable (sold out or disabled)")
                self.result.cart_status = "skipped"
                return

            await self._handle_variants(page)

            add_to_cart_success = await self._add_to_cart(page, platform)
            if not add_to_cart_success:
                self.result.errors.append("Failed to add product to cart")
                self.result.cart_status = "failed"
                return

            cart_url = await self._navigate_to_cart(page)
            if not cart_url:
                self.result.errors.append("Failed to navigate to cart")
                self.result.cart_status = "not_found"
                return

            nav_result = await navigate_with_retry(
                page,
                cart_url,
                session_id=self.session_id,
                repository=self.repository,
                page_type="cart",
                viewport=self.viewport,
                domain=self.domain,
            )
            if not nav_result.success:
                self.result.errors.append(f"Cart navigation failed: {nav_result.error_summary}")
                self.result.cart_status = "failed"
                return

            await wait_for_page_ready(page, soft_timeout=10000)
            await scroll_sequence(page)
            await dismiss_popups(page)

            if not await self._validate_cart_page(page):
                self.result.errors.append("Cart page validation failed")
                self.result.cart_status = "invalid"
                return

            await self._capture_page_payloads(page, "cart")
            self.result.cart_url = cart_url
            self.result.cart_status = "found"

        except Exception as e:
            logger.error("cart_navigation_failed", error=str(e))
            self.result.errors.append(f"Cart navigation error: {str(e)}")
            self.result.cart_status = "failed"
        finally:
            if page:
                await page.close()
            if context:
                await context.close()

    async def _find_best_add_to_cart_button(self, page: Page, platform: str) -> Optional[str]:
        """Find the most likely add-to-cart button."""
        platform_bias_selectors = []
        if platform == "shopify":
            platform_bias_selectors = [
                'form[action*="/cart/add"] button[type="submit"]',
                'form[action*="/cart/add"] [name="add"]',
            ]
        elif platform == "woocommerce":
            platform_bias_selectors = [
                "form.variations_form .single_add_to_cart_button",
                "form.cart .single_add_to_cart_button",
            ]

        generic_selectors = [
            'button:has-text("Add to Cart")',
            'button:has-text("Add to Bag")',
            'button:has-text("Add to Basket")',
            '[name="add-to-cart"]',
            '[class*="add-to-cart"]',
            '[class*="addToCart"]',
        ]

        candidates = platform_bias_selectors + generic_selectors

        for selector in candidates:
            try:
                locator = page.locator(selector).first
                if await locator.count() == 0:
                    continue
                if not await locator.is_visible():
                    continue
                if not await locator.is_enabled():
                    continue
                return selector
            except Exception:
                continue

        return None

    async def _click_add_to_cart_with_strategies(
        self,
        page: Page,
        selector: str,
        platform: str,
        attempt: int,
    ) -> bool:
        """Click add-to-cart using a ladder of strategies."""
        strategies = ["scroll_click", "hover_click", "wait_click", "js_click", "force_click"]

        for strategy in strategies:
            try:
                locator = page.locator(selector).first
                if await locator.count() == 0:
                    logger.info(
                        "add_to_cart_locator_missing",
                        selector=selector,
                        platform=platform,
                        strategy=strategy,
                        attempt=attempt,
                    )
                    return False

                if strategy == "scroll_click":
                    await locator.scroll_into_view_if_needed()
                    await locator.click()
                elif strategy == "hover_click":
                    await locator.scroll_into_view_if_needed()
                    await locator.hover()
                    await locator.click()
                elif strategy == "wait_click":
                    await locator.wait_for(state="visible", timeout=3000)
                    await asyncio.sleep(0.3)
                    await locator.click()
                elif strategy == "js_click":
                    handle = await locator.element_handle()
                    if handle:
                        await page.evaluate("(el) => el.click()", handle)
                    else:
                        continue
                elif strategy == "force_click":
                    await locator.scroll_into_view_if_needed()
                    await locator.click(force=True)
                else:
                    continue

                logger.info(
                    "add_to_cart_click_attempt",
                    selector=selector,
                    platform=platform,
                    strategy=strategy,
                    attempt=attempt,
                    url_before=page.url,
                )
                return True
            except Exception as e:
                logger.warning(
                    "add_to_cart_click_strategy_failed",
                    selector=selector,
                    platform=platform,
                    strategy=strategy,
                    attempt=attempt,
                    error=str(e),
                )
                continue

        return False

    async def _wait_for_platform_add_to_cart_response(
        self, page: Page, platform: str, timeout_ms: int
    ) -> bool:
        """Best-effort network-level add-to-cart success signal."""
        if platform not in ("shopify", "woocommerce"):
            return False

        timeout_ms = max(timeout_ms, 500)

        def _matcher(response) -> bool:
            url = response.url.lower()
            if platform == "shopify":
                return "/cart/add" in url
            if platform == "woocommerce":
                return "wc-ajax=add_to_cart" in url or "/add-to-cart/" in url
            return False

        try:
            resp = await page.wait_for_response(_matcher, timeout=timeout_ms)
            return resp.ok
        except Exception:
            return False

    async def _add_to_cart(self, page: Page, platform: str) -> bool:
        """State-machine style add-to-cart with retries."""
        backoff_schedule = [0.8, 1.5, 2.5]

        for attempt, backoff in enumerate(backoff_schedule, start=1):
            await self._stabilize_pdp_before_atc(page)
            await self._handle_variants(page)

            selector = await self._find_best_add_to_cart_button(page, platform)
            if not selector:
                logger.info("add_to_cart_button_not_found", platform=platform, attempt=attempt)
                await asyncio.sleep(backoff)
                continue

            cart_badge_before = await self._get_cart_badge_count(page)
            initial_url = page.url

            drawer_visible_before, drawer_items_before = await self._get_cart_drawer_state(page)
            view_cta_before = await self._get_view_cart_checkout_count(page)
            cart_like_before = await self._validate_cart_page(page)

            clicked = await self._click_add_to_cart_with_strategies(
                page=page,
                selector=selector,
                platform=platform,
                attempt=attempt,
            )
            if not clicked:
                await asyncio.sleep(backoff)
                continue

            network_success = await self._wait_for_platform_add_to_cart_response(
                page, platform, int(backoff * 1000)
            )
            await asyncio.sleep(backoff)

            success = await self._confirm_add_to_cart_success(
                page,
                initial_url,
                cart_badge_before,
                drawer_visible_before,
                drawer_items_before,
                view_cta_before,
                cart_like_before,
            )
            success = success or network_success

            logger.info(
                "add_to_cart_attempt_result",
                platform=platform,
                attempt=attempt,
                success=success,
                backoff=backoff,
                url_after=page.url,
            )
            self.repository.create_log(
                session_id=self.session_id,
                level="info",
                event_type="navigation",
                message="Add to cart attempt",
                details={
                    "platform": platform,
                    "attempt": attempt,
                    "success": success,
                    "backoff": backoff,
                    "url_before": initial_url,
                    "url_after": page.url,
                    "cart_badge_before": cart_badge_before,
                },
            )

            if success:
                logger.info("add_to_cart_success", platform=platform, attempt=attempt)
                self.repository.create_log(
                    session_id=self.session_id,
                    level="info",
                    event_type="navigation",
                    message="Product added to cart",
                    details={"platform": platform, "attempt": attempt},
                )
                return True

        return False

    async def _confirm_add_to_cart_success(
        self,
        page: Page,
        initial_url: str,
        cart_badge_before: Optional[int],
        drawer_visible_before: bool,
        drawer_items_before: int,
        view_cta_before: int,
        cart_like_before: bool,
    ) -> bool:
        """Confirm add to cart success by comparing before/after signals."""
        url_changed = page.url != initial_url
        url_cart_like = any(
            token in page.url.lower() for token in ["/cart", "/basket", "/bag"]
        )
        if url_changed and url_cart_like:
            return True

        cart_badge_after = await self._get_cart_badge_count(page)
        if cart_badge_before is not None and cart_badge_after is not None:
            if cart_badge_after > cart_badge_before:
                return True

        drawer_visible_after, drawer_items_after = await self._get_cart_drawer_state(page)
        if drawer_visible_after and (
            not drawer_visible_before or drawer_items_after > max(drawer_items_before, 0)
        ):
            return True

        toast_selectors = [
            ':has-text("added to cart")',
            ':has-text("added to bag")',
            '[class*="toast"]',
            '[class*="notification"]',
        ]
        for selector in toast_selectors:
            try:
                if await page.locator(selector).first.count() > 0:
                    return True
            except Exception:
                continue

        view_cart_or_checkout_after = await self._get_view_cart_checkout_count(page)
        if view_cart_or_checkout_after > view_cta_before:
            return True

        cart_like_after = await self._validate_cart_page(page)
        if cart_like_after and not cart_like_before:
            return True

        if await self._has_mini_cart_cart_state(page):
            return True

        return False

    async def _get_cart_badge_count(self, page: Page) -> Optional[int]:
        """Get cart badge count if present."""
        badge_selectors = [
            '[class*="cart-count"]',
            '[class*="cart-badge"]',
            "[data-cart-count]",
            '[aria-label*="cart" i]',
        ]
        for selector in badge_selectors:
            try:
                badge = page.locator(selector).first
                if await badge.is_visible():
                    text = await badge.inner_text()
                    if text:
                        match = re.search(r"\d+", text)
                        if match:
                            return int(match.group())
            except Exception:
                continue
        return None

    async def _get_cart_drawer_state(self, page: Page) -> tuple[bool, int]:
        """Return whether a cart drawer is visible and its item count."""
        drawer_selectors = [
            '[class*="cart-drawer"]',
            '[class*="cart-sidebar"]',
            '[id*="cart-drawer"]',
            '[class*="mini-cart"]',
        ]
        for selector in drawer_selectors:
            drawer = page.locator(selector).first
            try:
                if await drawer.count() > 0 and await drawer.is_visible():
                    items = await drawer.locator(
                        "[class*='cart-item'], [class*='cart__item'], [data-cart-item], tr.cart_item"
                    ).count()
                    return True, items
            except Exception:
                continue
        return False, 0

    async def _get_view_cart_checkout_count(self, page: Page) -> int:
        """Count visible view-cart / checkout CTAs."""
        locator = page.locator(
            'a:has-text("View cart"), a:has-text("View Cart"), button:has-text("View cart"), '
            'a:has-text("Checkout"), button:has-text("Checkout")'
        )
        try:
            return await locator.count()
        except Exception:
            return 0

    async def _navigate_to_cart(self, page: Page) -> Optional[str]:
        """Navigate to cart page."""
        cart_state_type, container_selector, signals = await self._classify_cart_state(page)
        if cart_state_type != "not_found":
            logger.info(
                "cart_state_detected",
                cart_state_type=cart_state_type,
                container_selector=container_selector,
                signals=signals,
            )
            self.repository.create_log(
                session_id=self.session_id,
                level="info",
                event_type="navigation",
                message="Cart state detected",
                details={
                    "cart_state_type": cart_state_type,
                    "container_selector": container_selector,
                    "signals": signals,
                },
            )
            self.result.cart_state_type = cart_state_type
            return page.url

        drawer_cart_selectors = [
            '[class*="cart-drawer"] a:has-text("View cart")',
            '[class*="cart-drawer"] a:has-text("Checkout")',
            '[class*="cart-sidebar"] a:has-text("View cart")',
        ]
        for selector in drawer_cart_selectors:
            try:
                link = page.locator(selector).first
                if await link.is_visible():
                    href = await link.get_attribute("href")
                    if href:
                        url = normalize_internal_url(href, self.base_url)
                        if url:
                            return url
            except Exception:
                continue

        view_cart_selectors = [
            'a:has-text("View cart")',
            'a:has-text("View Cart")',
            'button:has-text("View cart")',
            '[href*="/cart"]',
        ]
        for selector in view_cart_selectors:
            try:
                link = page.locator(selector).first
                if await link.is_visible():
                    href = await link.get_attribute("href")
                    if href:
                        url = normalize_internal_url(href, self.base_url)
                        if url:
                            return url
            except Exception:
                continue

        cart_icon_selectors = [
            '[class*="cart-icon"]',
            '[aria-label*="cart" i]',
            '[href*="/cart"]',
        ]
        for selector in cart_icon_selectors:
            try:
                icon = page.locator(selector).first
                if await icon.is_visible():
                    href = await icon.get_attribute("href")
                    if href:
                        url = normalize_internal_url(href, self.base_url)
                        if url:
                            return url
                    await icon.click()
                    await asyncio.sleep(2)
                    if "/cart" in page.url.lower() or "/basket" in page.url.lower():
                        return page.url
            except Exception:
                continue

        common_cart_paths = ["/cart", "/basket", "/bag"]
        base_parsed = urlparse(self.base_url)
        for path in common_cart_paths:
            cart_url = f"{base_parsed.scheme}://{base_parsed.netloc}{path}"
            try:
                nav_result = await navigate_with_retry(
                    page,
                    cart_url,
                    session_id=self.session_id,
                    repository=self.repository,
                    page_type="cart",
                    viewport=self.viewport,
                    domain=self.domain,
                )
                if nav_result.success:
                    return cart_url
            except Exception:
                continue

        return None

    async def _find_cart_from_post_atc_state(self, page: Page) -> Optional[str]:
        """Alias for cart discovery after confirmed add-to-cart."""
        return await self._navigate_to_cart(page)

    async def _validate_cart_page(self, page: Page) -> bool:
        """Validate cart page."""
        body_text = await page.inner_text("body")
        has_keywords = bool(
            re.search(
                r"(line item|cart item|subtotal|total|checkout)",
                body_text,
                re.I,
            )
        )
        line_item_locators = [
            "tr.cart_item",
            "[class*='cart-item']",
            "[class*='cart__row']",
            "[data-cart-item]",
        ]
        has_cart_rows = False
        for selector in line_item_locators:
            try:
                if await page.locator(selector).first.count() > 0:
                    has_cart_rows = True
                    break
            except Exception:
                continue

        has_checkout_cta = (
            await page.locator(
                'button:has-text("Checkout"), a:has-text("Checkout"), button:has-text("Proceed")'
            ).first.count()
            > 0
        )

        signals_true = [has_keywords, has_cart_rows, has_checkout_cta]
        return sum(1 for s in signals_true if s) >= 2
    async def _detect_visible_cart_container(self, page: Page) -> tuple[Optional[str], Optional[str]]:
        """Detect a visible cart container (page or overlay) and return (type, selector)."""
        container_patterns = [
            ("drawer", "[class*='cart-drawer'], [id*='cart-drawer']"),
            ("drawer", "[class*='bag-drawer'], [class*='basket-drawer']"),
            ("sidebar", "[class*='cart-sidebar'], [class*='basket-sidebar'], [class*='bag-sidebar']"),
            ("mini_cart", "[class*='mini-cart'], [id*='mini-cart']"),
            ("flyout", "[class*='flyout-cart'], [class*='flyout-bag']"),
            ("offcanvas", "[class*='offcanvas-cart'], [class*='off-canvas-cart']"),
            ("overlay", "[class*='cart-overlay'], [class*='basket-overlay']"),
            ("header_cart", "[class*='header-cart'], [id*='header-cart']"),
        ]

        for state_type, selector in container_patterns:
            locator = page.locator(selector)
            try:
                count = await locator.count()
                if count == 0:
                    continue
                visible = await locator.first.is_visible()
                if not visible:
                    continue
                return state_type, selector
            except Exception:
                continue

        return None, None

    async def _is_real_cart_container(self, container) -> tuple[bool, list[str]]:
        """Check whether a locator is a real cart container with strong evidence."""
        signals: list[str] = []
        try:
            if not await container.count() or not await container.first.is_visible():
                return False, signals
        except Exception:
            return False, signals

        locator = container.first

        try:
            items = await locator.locator(
                "tr.cart_item, [class*='cart-item'], [class*='cart__row'], [data-cart-item]"
            ).count()
            if items > 0:
                signals.append("line_items")
        except Exception:
            pass

        try:
            text = (await locator.inner_text()).lower()
        except Exception:
            text = ""

        if any(k in text for k in ["subtotal", "total"]):
            signals.append("totals")

        try:
            qty_controls = await locator.locator(
                "input[name*='quantity' i], input[type='number'], button:has-text('+'), button:has-text('-')"
            ).count()
            if qty_controls > 0:
                signals.append("quantity_controls")
        except Exception:
            pass

        try:
            remove_controls = await locator.locator(
                "button:has-text('Remove'), a:has-text('Remove'), [class*='remove']"
            ).count()
            if remove_controls > 0:
                signals.append("remove_controls")
        except Exception:
            pass

        try:
            checkout_cta = await locator.locator(
                'button:has-text("Checkout"), a:has-text("Checkout"), button:has-text("Proceed")'
            ).count()
            if checkout_cta > 0:
                signals.append("checkout_cta")
        except Exception:
            pass

        try:
            view_cart_cta = await locator.locator(
                'a:has-text("View cart"), a:has-text("View Cart"), button:has-text("View cart")'
            ).count()
            if view_cart_cta > 0:
                signals.append("view_cart_cta")
        except Exception:
            pass

        is_real = len(signals) > 0 and (
            "line_items" in signals
            or "totals" in signals
            or "checkout_cta" in signals
        )
        return is_real, signals

    async def _classify_cart_state(self, page: Page) -> tuple[str, Optional[str], list[str]]:
        """Classify cart state as page / mini_cart / drawer / header_cart / unknown / not_found."""
        if await self._validate_cart_page(page):
            return "page", None, ["cart_page_valid"]

        state_type, selector = await self._detect_visible_cart_container(page)
        if not state_type or not selector:
            return "not_found", None, []

        container = page.locator(selector)
        is_real, signals = await self._is_real_cart_container(container)
        if not is_real:
            return "not_found", None, []

        if state_type == "header_cart":
            return "header_cart", selector, signals
        if state_type in ("drawer", "sidebar", "overlay", "offcanvas", "flyout"):
            return "drawer", selector, signals
        if state_type == "mini_cart":
            return "mini_cart", selector, signals

        return "unknown", selector, signals

    async def _navigate_to_checkout(self, browser: Browser) -> None:
        """Navigate to checkout page."""
        bind_request_context(
            session_id=str(self.session_id),
            page_type="checkout",
            viewport=self.viewport,
            domain=self.domain,
        )

        context = await create_browser_context(browser, self.viewport)
        page = None
        try:
            page = await context.new_page()

            nav_result = await navigate_with_retry(
                page,
                self.result.cart_url,
                session_id=self.session_id,
                repository=self.repository,
                page_type="cart",
                viewport=self.viewport,
                domain=self.domain,
            )
            if not nav_result.success:
                self.result.errors.append("Failed to navigate to cart for checkout")
                self.result.checkout_status = "failed"
                return

            await wait_for_page_ready(page, soft_timeout=10000)

            checkout_url = await self._find_checkout_from_cart_state(page)
            if not checkout_url:
                self.result.errors.append("Checkout URL not found")
                self.result.checkout_status = "not_found"
                return

            nav_result = await navigate_with_retry(
                page,
                checkout_url,
                session_id=self.session_id,
                repository=self.repository,
                page_type="checkout",
                viewport=self.viewport,
                domain=self.domain,
            )
            if not nav_result.success:
                self.result.errors.append(f"Checkout navigation failed: {nav_result.error_summary}")
                self.result.checkout_status = "failed"
                return

            await wait_for_page_ready(page, soft_timeout=10000)
            await scroll_sequence(page)
            await dismiss_popups(page)

            blocker = await self._detect_checkout_blockers(page)
            if blocker:
                self.result.errors.append(f"Checkout blocked: {blocker}")
                self.result.checkout_status = "blocked"
                return

            if not await self._validate_checkout_page(page):
                self.result.errors.append("Checkout page validation failed")
                self.result.checkout_status = "invalid"
                return

            await self._capture_page_payloads(page, "checkout")
            self.result.checkout_url = checkout_url
            self.result.checkout_status = "found"

        except Exception as e:
            logger.error("checkout_navigation_failed", error=str(e))
            self.result.errors.append(f"Checkout navigation error: {str(e)}")
            self.result.checkout_status = "failed"
        finally:
            if page:
                await page.close()
            if context:
                await context.close()

    async def _find_checkout_url(self, page: Page) -> Optional[str]:
        """Find checkout URL from cart page."""
        checkout_selectors = [
            'button:has-text("Checkout")',
            'button:has-text("Secure checkout")',
            'button:has-text("Proceed to checkout")',
            'a:has-text("Checkout")',
            '[href*="/checkout"]',
        ]
        for selector in checkout_selectors:
            try:
                button = page.locator(selector).first
                if await button.is_visible():
                    href = await button.get_attribute("href")
                    if href:
                        url = normalize_internal_url(href, self.base_url)
                        if url:
                            return url
                    await button.click()
                    await asyncio.sleep(2)
                    if "/checkout" in page.url.lower():
                        return page.url
            except Exception:
                continue

        base_parsed = urlparse(self.base_url)
        checkout_url = f"{base_parsed.scheme}://{base_parsed.netloc}/checkout"
        try:
            nav_result = await navigate_with_retry(
                page,
                checkout_url,
                session_id=self.session_id,
                repository=self.repository,
                page_type="checkout",
                viewport=self.viewport,
                domain=self.domain,
            )
            if nav_result.success:
                return checkout_url
        except Exception:
            pass

        return None

    async def _find_checkout_from_cart_state(self, page: Page) -> Optional[str]:
        """Find checkout URL from any cart state (page, drawer, mini-cart, header cart)."""
        cart_state_type, selector, signals = await self._classify_cart_state(page)

        if cart_state_type == "not_found":
            return await self._find_checkout_url(page)

        logger.info(
            "checkout_from_cart_state_attempt",
            cart_state_type=cart_state_type,
            container_selector=selector,
            signals=signals,
        )

        container = page if cart_state_type == "page" or not selector else page.locator(selector)

        try:
            checkout_loc = container.locator(
                'button:has-text("Checkout"), a:has-text("Checkout"), button:has-text("Proceed")'
            ).first
            if await checkout_loc.count() > 0 and await checkout_loc.is_visible():
                href = await checkout_loc.get_attribute("href")
                if href:
                    return normalize_internal_url(href, self.base_url)
                await checkout_loc.click()
                await asyncio.sleep(2)
                if "/checkout" in page.url.lower():
                    return page.url
        except Exception:
            pass

        return await self._find_checkout_url(page)

    async def _detect_checkout_blockers(self, page: Page) -> Optional[str]:
        """Detect checkout blockers."""
        body_text = await page.inner_text("body").lower()
        title = await page.title()

        blockers = {
            "login_required": ["sign in", "log in", "login required", "create account"],
            "region_restriction": ["not available", "region", "country", "shipping"],
            "password_protected": ["password", "protected"],
            "out_of_stock": ["out of stock", "sold out", "unavailable"],
            "captcha": ["captcha", "verify", "challenge"],
        }

        combined = f"{title} {body_text}".lower()
        for blocker_type, keywords in blockers.items():
            if any(keyword in combined for keyword in keywords):
                return blocker_type

        return None

    async def _validate_checkout_page(self, page: Page) -> bool:
        """Validate checkout page."""
        body_text = await page.inner_text("body")
        has_form_fields = bool(
            re.search(
                r"(email|address|payment|checkout|billing|shipping)",
                body_text,
                re.I,
            )
        )
        has_payment_section = (
            await page.locator(
                '[class*="payment"], [class*="checkout"], '
                'input[type="email"], input[name*="address"]'
            ).first.count()
            > 0
        )
        has_step_indicator = (
            await page.locator(
                '[class*="step"], [class*="progress"], [aria-label*="step" i]'
            ).first.count()
            > 0
        )

        return has_form_fields or has_payment_section or has_step_indicator

    async def _capture_page_payloads(self, page: Page, page_type: str) -> None:
        """Capture payloads for a page using existing artifact methods."""
        try:
            page_data = self.repository.get_page_by_session_type_viewport(
                self.session_id, page_type, self.viewport
            )
            if not page_data:
                page_data = self.repository.create_page(
                    session_id=self.session_id,
                    page_type=page_type,
                    viewport=self.viewport,
                    status="pending",
                )
            page_id = page_data["id"]

            if page_type == "product":
                self.result.product_page_id = page_id
            elif page_type == "cart":
                self.result.cart_page_id = page_id
            elif page_type == "checkout":
                self.result.checkout_page_id = page_id

            await asyncio.sleep(2)
            visible_text = await page.inner_text("body")
            visible_text = normalize_whitespace(visible_text)

            try:
                screenshot_bytes = await page.screenshot(type="png", full_page=True)
            except Exception:
                screenshot_bytes = None

            if page_type == "product":
                features = await extract_features_json_pdp(page)
            else:
                features = await extract_features_json(page)

            save_screenshot(
                self.repository,
                self.session_id,
                page_id,
                page_type,
                self.viewport,
                self.domain,
                screenshot_bytes,
            )
            save_visible_text(
                self.repository,
                self.session_id,
                page_id,
                page_type,
                self.viewport,
                self.domain,
                visible_text,
            )
            save_features_json(
                self.repository,
                self.session_id,
                page_id,
                page_type,
                self.viewport,
                self.domain,
                features,
            )

            html_content = await page.content()
            save_html_gz(
                self.repository,
                self.session_id,
                page_id,
                page_type,
                self.viewport,
                self.domain,
                html_content,
            )

            if page_type == "product":
                analyze_product_html(
                    html_content,
                    self.session_id,
                    page_id,
                    page_type,
                    self.viewport,
                    self.domain,
                    self.repository,
                )

            self.repository.update_page(page_id, status="ok", load_timings={})

        except Exception as e:
            logger.error(
                "payload_capture_failed",
                page_type=page_type,
                error=str(e),
                error_type=type(e).__name__,
            )
            self.result.errors.append(f"Payload capture failed for {page_type}: {str(e)}")

    async def _get_html_analysis_json(self) -> Optional[dict]:
        """Load HTML analysis JSON from file (shared for both desktop and mobile)."""
        try:
            config = get_config()
            artifacts_root = Path(config.artifacts_dir)
            normalized_domain = (self.domain or "").strip().lower()
            if normalized_domain.startswith("www."):
                normalized_domain = normalized_domain[4:]
            normalized_domain = normalized_domain or "unknown-domain"
            root_name = f"{normalized_domain}__{self.session_id}"
            json_path = artifacts_root / root_name / "pdp" / "html_analysis.json"

            if json_path.exists():
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["_file_path"] = str(json_path.absolute())
                return data
        except Exception as e:
            logger.warning("failed_to_load_html_analysis_json", error=str(e))
        return None

    async def _run_checkout_flow_with_json(self, page: Page, html_analysis_json: dict) -> None:
        """Run checkout flow using HTML analysis JSON."""
        try:
            import sys

            config = get_config()
            if config.html_analysis_mode.lower() == "manual":
                json_file_path = html_analysis_json.get("_file_path")
                if json_file_path:
                    json_path = Path(json_file_path)
                    flag_file = json_path.parent / "checkout_ready.flag"

                    print("\n" + "=" * 80)
                    print("CHECKOUT FLOW - MANUAL MODE")
                    print("=" * 80)
                    print("\nHTML analysis JSON file:")
                    print(f"  {json_file_path}")
                    print("\nTo proceed with checkout flow, create this flag file:")
                    print(f"  {flag_file.absolute()}")
                    print("\nWaiting for flag file...")
                    print("(The process will continue automatically when the file exists)")
                    sys.stdout.flush()

                    import time

                    max_wait_seconds = 3600
                    wait_interval = 2
                    waited = 0

                    while not flag_file.exists():
                        if waited >= max_wait_seconds:
                            logger.warning("checkout_flow_manual_timeout")
                            timeout_msg = (
                                f"\nWARNING: Timeout after {max_wait_seconds} seconds, "
                                "proceeding anyway..."
                            )
                            print(timeout_msg)
                            break
                        time.sleep(wait_interval)
                        waited += wait_interval
                        if waited % 30 == 0:
                            print(f"Still waiting... ({waited}s elapsed)")
                            sys.stdout.flush()

                    if flag_file.exists():
                        print("\n✓ Flag file found! Proceeding with checkout flow...")
                        sys.stdout.flush()
                        flag_file.unlink()

            json_file_path = html_analysis_json.get("_file_path")
            if json_file_path:
                with open(json_file_path, "r", encoding="utf-8") as f:
                    analysis_data = json.load(f)
            else:
                analysis_data = html_analysis_json

            checkout_result = await run_checkout_flow(
                page,
                self.result.product_url,
                analysis_data,
                self.session_id,
                self.viewport,
                self.domain,
                self.repository,
            )

            if checkout_result.get("add_to_cart", {}).get("status") == "completed":
                self.result.cart_status = "found"
            if checkout_result.get("checkout_navigation", {}).get("status") == "completed":
                self.result.checkout_status = "found"

            for error in checkout_result.get("errors", []):
                self.result.errors.append(error)

        except Exception as e:
            logger.error(
                "checkout_flow_integration_failed",
                error=str(e),
                error_type=type(e).__name__,
                session_id=str(self.session_id),
            )
            self.result.errors.append(f"Checkout flow error: {str(e)}")
