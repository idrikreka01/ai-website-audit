"""
Browser context creation for crawl (viewport, UA, timezone).

Per TECH_SPEC_V1.md; no behavior change.
"""

from __future__ import annotations

from playwright.async_api import Browser, BrowserContext

from worker.crawl.constants import VIEWPORT_CONFIGS, Viewport


STEALTH_INIT_SCRIPT = """
(() => {
  try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  } catch (e) {}

  try {
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
  } catch (e) {}

  try {
    Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
  } catch (e) {}

  try {
    window.chrome = window.chrome || { runtime: {} };
  } catch (e) {}

  try {
    const originalQuery = navigator.permissions && navigator.permissions.query;
    if (originalQuery) {
      navigator.permissions.query = (parameters) => {
        if (parameters && parameters.name === 'notifications') {
          return Promise.resolve({ state: 'denied', onchange: null });
        }
        return originalQuery(parameters);
      };
    }
  } catch (e) {}
})();
"""


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

    await context.add_init_script(STEALTH_INIT_SCRIPT)
    return context
