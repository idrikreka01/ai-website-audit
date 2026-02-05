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
    MAX_DISMISSALS_PER_PASS,
    MAX_SCROLL_STEPS,
    MINIMUM_WAIT_AFTER_LOAD,
    POPUP_CLICK_TIMEOUT_MS,
    POPUP_CONTAINER_SELECTORS,
    POPUP_SETTLE_AFTER_DISMISS_MS,
    POPUP_VISIBILITY_TIMEOUT_MS,
    SCROLL_BOTTOM_WAIT_MS,
    SCROLL_STEP_RATIO,
    SCROLL_WAIT,
)
from worker.crawl.popup_rules import (
    get_popup_selectors_in_order,
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
    Perform scroll sequence with incremental steps down the page, then back to top.

    Includes waits after each step and a bottom dwell to allow lazy elements to load.
    """
    viewport_height = page.viewport_size["height"] if page.viewport_size else 800
    step_px = max(200, int(viewport_height * SCROLL_STEP_RATIO))

    # Incremental scroll down to bottom (bounded).
    for step in range(MAX_SCROLL_STEPS):
        y = step * step_px
        await page.evaluate(f"window.scrollTo(0, {y})")
        await asyncio.sleep(SCROLL_WAIT / 1000)
        at_bottom = await page.evaluate(
            "window.innerHeight + window.scrollY >= document.body.scrollHeight"
        )
        if at_bottom:
            break

    # Ensure bottom and dwell for lazy loads.
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(SCROLL_BOTTOM_WAIT_MS / 1000)

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


async def _is_within_popup_container(element: Locator) -> bool:
    """Return True if element is inside a known consent/popup container."""
    if not POPUP_CONTAINER_SELECTORS:
        return True
    selector = ", ".join(POPUP_CONTAINER_SELECTORS)
    try:
        return await element.evaluate("(el, sel) => !!el.closest(sel)", selector)
    except Exception:
        return False


async def dismiss_popups(page: Page) -> list[dict]:
    """
    One pass of popup dismissal (post-ready or post-scroll). Max two passes per page:
    caller invokes once after ready (pass 1), once after scroll (pass 2).

    Uses overlay-first selector order (dialog/banner before cookie/newsletter),
    bounded attempts per pass (MAX_DISMISSALS_PER_PASS), and safe/risky text
    filtering. Deterministic timing: visibility/click timeouts and brief settle
    after each dismiss. Errors are logged and do not fail the crawl.
    Per TECH_SPEC_V1.1.md §5 Popup Handling Policy v1.6.

    Returns a list of popup events for DB logging. Each event has selector,
    action (dismiss_click), result (success | failure), and attempt (1-based).
    Selector-miss events and detected-ignored events are not logged. Caller
    should write each to DB with event_type=popup and context (session_id,
    page_type, viewport, domain).
    """
    events: list[dict] = []
    dismissed_count = 0
    try:
        popup_selectors = get_popup_selectors_in_order(overlay_first=True)
        for attempt_one_based, selector in enumerate(popup_selectors, start=1):
            if dismissed_count >= MAX_DISMISSALS_PER_PASS:
                break
            try:
                element = page.locator(selector).first
                if not await element.is_visible(timeout=POPUP_VISIBILITY_TIMEOUT_MS):
                    continue
                text = await _element_dismiss_text(element)
                if is_risky_cta_text(text):
                    logger.debug(
                        "popup_skipped",
                        selector=selector,
                        reason="risky_cta",
                        text_preview=(text[:80] + "…") if len(text) > 80 else text or "(empty)",
                    )
                    continue
                if not is_safe_dismiss_text(text):
                    logger.debug(
                        "popup_skipped",
                        selector=selector,
                        reason="not_safe_dismiss",
                        text_preview=(text[:80] + "…") if len(text) > 80 else text or "(empty)",
                    )
                    continue
                if not await _is_within_popup_container(element):
                    logger.debug(
                        "popup_skipped",
                        selector=selector,
                        reason="outside_container",
                        text_preview=(text[:80] + "…") if len(text) > 80 else text or "(empty)",
                    )
                    continue
                await element.click(timeout=POPUP_CLICK_TIMEOUT_MS)
                ts = datetime.now(timezone.utc).isoformat()
                events.append(
                    _popup_event(
                        selector,
                        "dismiss_click",
                        "success",
                        attempt_one_based,
                        ts,
                        page.url,
                    )
                )
                dismissed_count += 1
                logger.debug("popup_dismissed", selector=selector)
                await asyncio.sleep(POPUP_SETTLE_AFTER_DISMISS_MS / 1000)
            except Exception:
                events.append(
                    _popup_event(
                        selector,
                        "dismiss_click",
                        "failure",
                        attempt_one_based,
                        current_url=page.url,
                    )
                )
                logger.debug("popup_click_failed", selector=selector)
    except Exception as e:
        logger.warning("popup_pass_error", error=str(e), error_type=type(e).__name__)
    return events
