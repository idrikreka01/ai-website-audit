"""
Playwright-based crawling helpers for homepage evidence capture.

This module implements the page-ready rules, scrolling, popup dismissal,
and artifact extraction per TECH_SPEC_V1.md.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Literal, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from shared.logging import get_logger


logger = get_logger(__name__)

Viewport = Literal["desktop", "mobile"]

# Viewport configurations
VIEWPORT_CONFIGS = {
    "desktop": {"width": 1920, "height": 1080},
    "mobile": {"width": 375, "height": 667},
}

# Timeout constants (in milliseconds)
NETWORK_IDLE_TIMEOUT = 800  # Network idle window
DOM_STABILITY_TIMEOUT = 1000  # DOM stability window
MINIMUM_WAIT_AFTER_LOAD = 500  # Minimum wait after load
HARD_TIMEOUT_MS = 30000  # Hard timeout cap per page
SCROLL_WAIT = 500  # Wait after each scroll


async def create_browser_context(
    browser: Browser,
    viewport: Viewport,
) -> BrowserContext:
    """
    Create a browser context with the specified viewport.

    Uses stable UA, viewport, and timezone for anti-bot considerations.
    """
    config = VIEWPORT_CONFIGS[viewport]

    context = await browser.new_context(
        viewport={"width": config["width"], "height": config["height"]},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        timezone_id="America/New_York",
        locale="en-US",
    )

    return context


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
    timings = {
        "navigation_start": start_time.isoformat(),
    }

    try:
        # Wait for network idle (800ms window)
        await page.wait_for_load_state("networkidle", timeout=soft_timeout)
        network_idle_time = datetime.now(timezone.utc)
        timings["network_idle"] = network_idle_time.isoformat()
        timings["network_idle_duration_ms"] = (
            (network_idle_time - start_time).total_seconds() * 1000
        )

        # Wait for DOM stability (1s window with no layout shifts)
        # Simple approach: wait for a period with no mutations
        await asyncio.sleep(DOM_STABILITY_TIMEOUT / 1000)
        dom_stable_time = datetime.now(timezone.utc)
        timings["dom_stable"] = dom_stable_time.isoformat()

        # Minimum wait after load
        await asyncio.sleep(MINIMUM_WAIT_AFTER_LOAD / 1000)
        ready_time = datetime.now(timezone.utc)
        timings["ready"] = ready_time.isoformat()
        timings["total_load_duration_ms"] = (
            (ready_time - start_time).total_seconds() * 1000
        )

    except PlaywrightTimeoutError:
        # Soft timeout - log warning but continue
        logger.warning(
            "page_ready_soft_timeout",
            timeout_ms=soft_timeout,
        )
        ready_time = datetime.now(timezone.utc)
        timings["ready"] = ready_time.isoformat()
        timings["total_load_duration_ms"] = (
            (ready_time - start_time).total_seconds() * 1000
        )
        timings["soft_timeout"] = True

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


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace: collapse multiples, trim."""
    import re

    # Collapse multiple whitespace to single space
    text = re.sub(r"\s+", " ", text)
    # Trim
    text = text.strip()
    return text


async def extract_features_json(page: Page) -> dict:
    """
    Extract minimum features JSON for homepage.

    Includes: meta, headings, ctas, navigation, schema_org, review_signals.
    """
    features = {
        "meta": {},
        "headings": {"h1": [], "h2": []},
        "ctas": [],
        "navigation": {"main_nav_links": [], "footer_links": []},
        "schema_org": {"product_detected": False},
        "review_signals": {
            "review_count_present": False,
            "rating_value_present": False,
        },
    }

    # Meta
    title = await page.title()
    features["meta"]["title"] = title

    # Meta description (non-blocking; may be absent)
    try:
        meta_desc = await page.locator('meta[name="description"]').get_attribute(
            "content", timeout=1000
        )
    except Exception:
        meta_desc = None
    if meta_desc:
        features["meta"]["meta_description"] = meta_desc

    # Canonical link (non-blocking; may be absent)
    try:
        canonical = await page.locator('link[rel="canonical"]').get_attribute(
            "href", timeout=1000
        )
    except Exception:
        canonical = None
    if canonical:
        features["meta"]["canonical_url"] = canonical

    # Headings
    h1_elements = await page.locator("h1").all()
    for h1 in h1_elements:
        text = await h1.inner_text()
        if text:
            features["headings"]["h1"].append(normalize_whitespace(text))

    h2_elements = await page.locator("h2").all()
    for h2 in h2_elements:
        text = await h2.inner_text()
        if text:
            features["headings"]["h2"].append(normalize_whitespace(text))

    # CTAs (simple heuristic: buttons/links with action words)
    cta_selectors = [
        'button:has-text("Buy")',
        'button:has-text("Add to Cart")',
        'a:has-text("Shop")',
        'a:has-text("Buy Now")',
        '[class*="cta"]',
        '[class*="button"]',
    ]
    for selector in cta_selectors:
        try:
            elements = await page.locator(selector).all()
            for elem in elements[:5]:  # Limit to first 5
                text = await elem.inner_text()
                href = await elem.get_attribute("href")
                if text:
                    features["ctas"].append(
                        {"text": normalize_whitespace(text), "href": href or ""}
                    )
        except Exception:
            continue

    # Navigation (simplified)
    nav_links = await page.locator("nav a, header a").all()
    for link in nav_links[:20]:  # Limit to first 20
        text = await link.inner_text()
        href = await link.get_attribute("href")
        if text and href:
            features["navigation"]["main_nav_links"].append(
                {"text": normalize_whitespace(text), "href": href}
            )

    footer_links = await page.locator("footer a").all()
    for link in footer_links[:20]:  # Limit to first 20
        text = await link.inner_text()
        href = await link.get_attribute("href")
        if text and href:
            features["navigation"]["footer_links"].append(
                {"text": normalize_whitespace(text), "href": href}
            )

    # Schema.org detection
    schema_scripts = await page.locator(
        'script[type="application/ld+json"]'
    ).all()
    for script in schema_scripts:
        try:
            content = await script.inner_text()
            if '"@type"' in content and "Product" in content:
                features["schema_org"]["product_detected"] = True
                break
        except Exception:
            continue

    # Review signals (simple detection)
    review_indicators = await page.locator(
        '[class*="review"], [class*="rating"], [class*="star"]'
    ).count()
    if review_indicators > 0:
        features["review_signals"]["review_count_present"] = True
        features["review_signals"]["rating_value_present"] = True

    return features
