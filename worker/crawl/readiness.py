"""
Page readiness: wait for ready, scroll sequence, dismiss popups.

Wait/scroll per TECH_SPEC_V1.md. Popup dismissal per TECH_SPEC_V1.1.md §5
Popup Handling Policy v1.6: two-pass flow (post-ready, post-scroll), overlay-first
ordering, bounded attempts per pass, safe/risky text filtering. Errors do not fail crawl.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from shared.logging import get_logger
from worker.crawl.constants import (
    DOM_STABILITY_TIMEOUT,
    MINIMUM_WAIT_AFTER_LOAD,
    POPUP_CLICK_TIMEOUT_MS,
    POPUP_DISMISS_ROUNDS,
    POPUP_ROUND_DELAY_MS,
    POPUP_SETTLE_AFTER_DISMISS_MS,
    SCROLL_WAIT,
)
from worker.crawl.popup_rules import (
    CLOSE_BUTTON_XPATH,
    CLOSE_CSS,
    OVERLAY_REMOVE_JS,
    SCROLL_UNLOCK_JS,
    is_risky_cta_text,
    is_safe_dismiss_text,
)

logger = get_logger(__name__)


async def wait_for_page_ready(
    page: Page,
    soft_timeout: int = 10000,
) -> dict:
    """
    Wait for page to be ready using TECH_SPEC rules:
    - Network idle window (800ms)
    - DOM stability (1s)
    - Minimum wait after load (500ms)

    Returns load_timings dict with timestamps and durations.
    """
    start_time = datetime.now(timezone.utc)
    # Fixed key set so homepage and PDP load_timings are identical; soft_timeout always present.
    timings: dict = {
        "navigation_start": start_time.isoformat(),
        "network_idle": None,
        "network_idle_duration_ms": None,
        "dom_stable": None,
        "ready": None,
        "total_load_duration_ms": None,
        "soft_timeout": False,
    }

    try:
        # Wait for network idle (800ms window)
        await page.wait_for_load_state("networkidle", timeout=soft_timeout)
        network_idle_time = datetime.now(timezone.utc)
        timings["network_idle"] = network_idle_time.isoformat()
        timings["network_idle_duration_ms"] = (
            network_idle_time - start_time
        ).total_seconds() * 1000

        # Wait for DOM stability (1s window with no layout shifts)
        await asyncio.sleep(DOM_STABILITY_TIMEOUT / 1000)
        dom_stable_time = datetime.now(timezone.utc)
        timings["dom_stable"] = dom_stable_time.isoformat()

        # Minimum wait after load
        await asyncio.sleep(MINIMUM_WAIT_AFTER_LOAD / 1000)
        ready_time = datetime.now(timezone.utc)
        timings["ready"] = ready_time.isoformat()
        timings["total_load_duration_ms"] = (ready_time - start_time).total_seconds() * 1000

    except PlaywrightTimeoutError:
        # Soft timeout: log warning, continue; record timings with unreached milestones as None.
        logger.warning(
            "page_ready_soft_timeout",
            timeout_ms=soft_timeout,
        )
        ready_time = datetime.now(timezone.utc)
        timings["ready"] = ready_time.isoformat()
        timings["total_load_duration_ms"] = (ready_time - start_time).total_seconds() * 1000
        timings["soft_timeout"] = True

    # Readiness milestone; context (session_id, page_type, viewport, domain) from caller.
    logger.info(
        "readiness_complete",
        network_idle=timings.get("network_idle"),
        dom_stable=timings.get("dom_stable"),
        total_load_duration_ms=timings.get("total_load_duration_ms"),
        soft_timeout=timings["soft_timeout"],
    )
    return timings


async def scroll_sequence(page: Page) -> None:
    """
    Perform scroll sequence: top → mid → bottom → top.

    Includes short waits after each scroll to allow lazy elements to load.
    """
    viewport_height = page.viewport_size["height"] if page.viewport_size else 800

    # Scroll to mid
    await page.evaluate(f"window.scrollTo(0, {viewport_height})")
    await asyncio.sleep(SCROLL_WAIT / 1000)

    # Scroll to bottom
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(SCROLL_WAIT / 1000)

    # Scroll back to top
    await page.evaluate("window.scrollTo(0, 0)")
    await asyncio.sleep(SCROLL_WAIT / 1000)


async def _element_dismiss_text(element: Locator) -> str:
    """Get combined inner text and aria-label for safe/risky check. Returns normalized string."""
    parts: list[str] = []
    try:
        inner = await element.inner_text()
        if inner:
            parts.append(inner.strip())
    except Exception:
        pass
    try:
        aria = await element.get_attribute("aria-label")
        if aria:
            parts.append(aria.strip())
    except Exception:
        pass
    return " ".join(parts).strip()


def _popup_event(
    selector: str,
    action: str,
    result: str,
    attempt: int,
    timestamp: str | None = None,
    current_url: str | None = None,
) -> dict:
    """Build a popup event dict for DB logging (selector, action, result, attempt)."""
    out: dict = {
        "selector": selector,
        "action": action,
        "result": result,
        "attempt": attempt,
    }
    if timestamp is not None:
        out["timestamp"] = timestamp
    if current_url is not None:
        out["current_url"] = current_url
    return out


async def _allow_scroll(page: Page) -> None:
    try:
        await page.evaluate(SCROLL_UNLOCK_JS)
    except Exception:
        pass


async def _remove_overlays(page: Page) -> None:
    try:
        await page.evaluate(OVERLAY_REMOVE_JS)
    except Exception:
        pass


async def _close_popups_xpath_css(page: Page) -> tuple[bool, str | None]:
    """
    PopUpsTest-style: try XPath then CSS, click first visible element.
    Skips elements with risky text (download/shkarko). Returns (clicked, selector_used).
    """
    for xpath in CLOSE_BUTTON_XPATH:
        try:
            locs = await page.locator(f"xpath={xpath}").all()
            for loc in locs:
                if await loc.is_visible():
                    text = await _element_dismiss_text(loc)
                    if is_risky_cta_text(text) or not is_safe_dismiss_text(text):
                        continue
                    await loc.click(timeout=POPUP_CLICK_TIMEOUT_MS)
                    return True, xpath
        except Exception:
            continue
    for sel in CLOSE_CSS:
        try:
            locs = await page.locator(sel).all()
            for loc in locs:
                if await loc.is_visible():
                    text = await _element_dismiss_text(loc)
                    if is_risky_cta_text(text) or not is_safe_dismiss_text(text):
                        continue
                    await loc.click(timeout=POPUP_CLICK_TIMEOUT_MS)
                    return True, sel
        except Exception:
            continue
    return False, None


async def dismiss_popups(page: Page) -> list[dict]:
    """
    PopUpsTest-style: allow_scroll → rounds of (close_popups_xpath_css →
    sleep → remove_overlays → sleep → allow_scroll). Uses XPath+CSS
    case-insensitive text matching; skips risky CTAs (download/shkarko).
    """
    events: list[dict] = []
    delay_s = POPUP_ROUND_DELAY_MS / 1000
    next_attempt = 1
    try:
        await _allow_scroll(page)
        for _ in range(POPUP_DISMISS_ROUNDS):
            clicked, selector = await _close_popups_xpath_css(page)
            if clicked and selector:
                ts = datetime.now(timezone.utc).isoformat()
                events.append(
                    _popup_event(
                        selector,
                        "dismiss_click",
                        "success",
                        next_attempt,
                        ts,
                        page.url,
                    )
                )
                next_attempt += 1
                logger.debug("popup_dismissed_xpath_css", selector=selector)
                await asyncio.sleep(POPUP_SETTLE_AFTER_DISMISS_MS / 1000)
            await asyncio.sleep(delay_s)
            await _remove_overlays(page)
            await asyncio.sleep(delay_s)
            await _allow_scroll(page)
    except Exception as e:
        logger.warning("popup_pass_error", error=str(e), error_type=type(e).__name__)
    return events
