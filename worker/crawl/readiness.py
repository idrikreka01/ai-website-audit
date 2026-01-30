"""
Page readiness: wait for ready, scroll sequence, dismiss popups.

Per TECH_SPEC_V1.md; no behavior change.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from shared.logging import get_logger
from worker.crawl.constants import DOM_STABILITY_TIMEOUT, MINIMUM_WAIT_AFTER_LOAD, SCROLL_WAIT

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


async def dismiss_popups(page: Page) -> list[dict]:
    """
    Attempt to dismiss common popups/cookie banners.

    Returns a list of dismissed popup info (selector, timestamp).
    """
    dismissed = []

    # Common popup/cookie banner selectors (simple heuristic)
    popup_selectors = [
        'button:has-text("Accept")',
        'button:has-text("Accept All")',
        'button:has-text("I Accept")',
        'button:has-text("OK")',
        '[id*="cookie"] button',
        '[class*="cookie"] button',
        '[id*="popup"] button[class*="close"]',
        '[class*="popup"] button[class*="close"]',
        '[aria-label*="close" i]',
        '[aria-label*="dismiss" i]',
    ]

    for selector in popup_selectors:
        try:
            element = page.locator(selector).first
            if await element.is_visible(timeout=1000):
                await element.click(timeout=2000)
                dismissed.append(
                    {
                        "selector": selector,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                logger.debug("popup_dismissed", selector=selector)
                # Small wait after dismissal
                await asyncio.sleep(200 / 1000)
        except Exception:
            # Selector didn't match or click failed - continue
            continue

    return dismissed
