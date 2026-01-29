"""
Browser context creation for crawl (viewport, UA, timezone).

Per TECH_SPEC_V1.md; no behavior change.
"""

from __future__ import annotations

from playwright.async_api import Browser, BrowserContext

from worker.crawl.constants import VIEWPORT_CONFIGS, Viewport


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
