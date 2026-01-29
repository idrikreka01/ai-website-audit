"""
Crawl runner: homepage and PDP viewport crawls (Playwright, extraction, artifact persistence).

Encapsulates crawl_homepage_viewport, crawl_pdp_viewport, crawl_homepage_async, crawl_pdp_async.
No behavior change.
"""

from __future__ import annotations

from uuid import UUID

from playwright.async_api import Browser, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from shared.logging import bind_request_context, get_logger
from worker.artifacts import (
    save_features_json,
    save_html_gz,
    save_screenshot,
    save_visible_text,
    should_store_html,
)
from worker.constants import HOMEPAGE_VIEWPORTS, PDP_VIEWPORTS
from worker.crawl import (
    MAX_PDP_CANDIDATES,
    create_browser_context,
    dismiss_popups,
    extract_features_json,
    extract_features_json_pdp,
    extract_pdp_candidate_links,
    normalize_whitespace,
    scroll_sequence,
    wait_for_page_ready,
)
from worker.low_confidence import evaluate_low_confidence, evaluate_low_confidence_pdp
from worker.repository import AuditRepository

logger = get_logger(__name__)


async def crawl_homepage_viewport(
    browser: Browser,
    url: str,
    session_id: UUID,
    page_type: str,
    viewport: str,
    repository: AuditRepository,
    mode: str,
    first_time: bool,
) -> tuple[bool, dict]:
    """
    Crawl homepage for a specific viewport.

    Returns (success: bool, page_data: dict with page_id, load_timings, etc.).
    """
    bind_request_context(
        session_id=str(session_id),
        page_type=page_type,
        viewport=viewport,
    )

    logger.info("crawl_started", url=url, viewport=viewport)

    page_data = repository.get_page_by_session_type_viewport(session_id, page_type, viewport)
    if not page_data:
        page_data = repository.create_page(
            session_id=session_id,
            page_type=page_type,
            viewport=viewport,
            status="pending",
        )
    page_id = page_data["id"]

    context = None
    page = None
    success = False
    load_timings = {}
    error_summary = None
    screenshot_failed = False
    screenshot_blank = False
    pdp_candidate_urls: list[str] = []

    try:
        context = await create_browser_context(browser, viewport)
        page = await context.new_page()

        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message=f"Navigating to {url}",
            details={"url": url, "viewport": viewport},
        )

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeoutError as e:
            error_summary = f"Navigation timeout: {str(e)}"
            logger.error("navigation_timeout", error=str(e))
            repository.create_log(
                session_id=session_id,
                level="error",
                event_type="timeout",
                message="Navigation timeout",
                details={"error": str(e)},
            )
            raise

        load_timings = await wait_for_page_ready(page, soft_timeout=10000)
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Page ready",
            details=load_timings,
        )

        dismissed = await dismiss_popups(page)
        if dismissed:
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="popup",
                message=f"Dismissed {len(dismissed)} popups",
                details={"dismissed": dismissed},
            )

        await scroll_sequence(page)
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Scroll sequence completed",
        )

        if page_type == "homepage" and viewport == "desktop":
            pdp_candidate_urls = await extract_pdp_candidate_links(
                page, url, max_candidates=MAX_PDP_CANDIDATES
            )
            logger.info(
                "candidate_links_extracted",
                session_id=str(session_id),
                viewport=viewport,
                count=len(pdp_candidate_urls),
                sample=pdp_candidate_urls[:5],
            )

        visible_text = await page.inner_text("body")
        visible_text = normalize_whitespace(visible_text)
        text_length = len(visible_text)

        features = await extract_features_json(page)
        has_h1 = len(features["headings"]["h1"]) > 0
        has_primary_cta = len(features["ctas"]) > 0

        try:
            screenshot_bytes = await page.screenshot(type="png", full_page=True)
            screenshot_failed = False
            screenshot_blank = len(screenshot_bytes) < 1000
        except Exception as e:
            screenshot_bytes = None
            screenshot_failed = True
            logger.warning("screenshot_failed", error=str(e))

        low_confidence, low_confidence_reasons = evaluate_low_confidence(
            has_h1=has_h1,
            has_primary_cta=has_primary_cta,
            visible_text_length=text_length,
            screenshot_failed=screenshot_failed,
            screenshot_blank=screenshot_blank,
        )

        store_html = should_store_html(first_time, mode, low_confidence, error_summary)

        if store_html:
            logger.info(
                "html_storage_triggered",
                first_time=first_time,
                mode=mode,
                low_confidence=low_confidence,
                has_error=error_summary is not None,
            )

        artifacts_saved = []

        name = save_screenshot(
            repository, session_id, page_id, page_type, viewport, screenshot_bytes
        )
        if name:
            artifacts_saved.append(name)

        artifacts_saved.append(
            save_visible_text(
                repository, session_id, page_id, page_type, viewport, visible_text
            )
        )
        artifacts_saved.append(
            save_features_json(
                repository, session_id, page_id, page_type, viewport, features
            )
        )

        if store_html:
            html_content = await page.content()
            artifacts_saved.append(
                save_html_gz(
                    repository, session_id, page_id, page_type, viewport, html_content
                )
            )

        repository.update_page(
            page_id,
            status="ok",
            load_timings=load_timings,
            low_confidence_reasons=low_confidence_reasons,
        )

        success = True
        logger.info(
            "crawl_completed",
            viewport=viewport,
            artifacts_saved=artifacts_saved,
            low_confidence=low_confidence,
        )

    except Exception as e:
        error_summary = str(e)
        logger.error("crawl_failed", error=str(e), error_type=type(e).__name__)
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="error",
            message=f"Crawl failed: {str(e)}",
            details={"error": str(e), "error_type": type(e).__name__},
        )
        repository.update_page(page_id, status="failed", load_timings=load_timings)
        success = False

    finally:
        if page:
            await page.close()
        if context:
            await context.close()

    out: dict = {
        "page_id": page_id,
        "load_timings": load_timings,
        "error_summary": error_summary,
    }
    if page_type == "homepage" and viewport == "desktop":
        out["pdp_candidate_urls"] = pdp_candidate_urls
    return success, out


async def crawl_pdp_viewport(
    browser: Browser,
    pdp_url: str,
    session_id: UUID,
    viewport: str,
    repository: AuditRepository,
    mode: str,
    first_time: bool,
) -> tuple[bool, dict]:
    """
    Crawl PDP for a specific viewport; capture screenshot, visible_text,
    features_json, optional html.gz. Update audit_pages and create artifact rows.

    Returns (success: bool, page_data: dict with page_id, load_timings, etc.).
    """
    page_type = "pdp"
    bind_request_context(
        session_id=str(session_id),
        page_type=page_type,
        viewport=viewport,
    )

    logger.info(
        "pdp_crawl_started",
        url=pdp_url,
        viewport=viewport,
        session_id=str(session_id),
    )
    repository.create_log(
        session_id=session_id,
        level="info",
        event_type="navigation",
        message="PDP crawl started",
        details={"url": pdp_url, "viewport": viewport},
    )

    page_data = repository.get_page_by_session_type_viewport(session_id, page_type, viewport)
    if not page_data:
        page_data = repository.create_page(
            session_id=session_id,
            page_type=page_type,
            viewport=viewport,
            status="pending",
        )
    page_id = page_data["id"]

    context = None
    page = None
    success = False
    load_timings: dict = {}
    error_summary = None
    screenshot_failed = False
    screenshot_blank = False

    try:
        context = await create_browser_context(browser, viewport)
        page = await context.new_page()

        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message=f"Navigating to PDP {pdp_url}",
            details={"url": pdp_url, "viewport": viewport},
        )
        try:
            await page.goto(pdp_url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeoutError as e:
            error_summary = f"Navigation timeout: {str(e)}"
            logger.error("pdp_crawl_failed", error=str(e), viewport=viewport)
            repository.create_log(
                session_id=session_id,
                level="error",
                event_type="timeout",
                message="PDP navigation timeout",
                details={"error": str(e)},
            )
            raise

        load_timings = await wait_for_page_ready(page, soft_timeout=10000)
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Page ready",
            details=load_timings,
        )

        dismissed = await dismiss_popups(page)
        if dismissed:
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="popup",
                message="Popup dismissed",
                details={"dismissed": dismissed},
            )

        await scroll_sequence(page)
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Scroll sequence completed",
        )

        visible_text = await page.inner_text("body")
        visible_text = normalize_whitespace(visible_text)
        text_length = len(visible_text)

        features = await extract_features_json_pdp(page)
        has_h1 = len(features["headings"]["h1"]) > 0
        has_primary_cta = len(features["ctas"]) > 0
        pdp_core = features.get("pdp_core", {})
        has_price = bool(
            pdp_core.get("price")
            or await page.locator(
                "[class*='price'], [data-price], [itemprop='price']"
            ).first.count()
            > 0
        )
        has_add_to_cart = bool(pdp_core.get("add_to_cart_present"))

        try:
            screenshot_bytes = await page.screenshot(type="png", full_page=True)
            screenshot_blank = len(screenshot_bytes) < 1000
        except Exception as e:
            screenshot_bytes = None
            screenshot_failed = True
            logger.warning("screenshot_failed", error=str(e))

        low_confidence, low_confidence_reasons = evaluate_low_confidence_pdp(
            has_h1=has_h1,
            has_primary_cta=has_primary_cta,
            has_price=has_price,
            has_add_to_cart=has_add_to_cart,
            visible_text_length=text_length,
            screenshot_failed=screenshot_failed,
            screenshot_blank=screenshot_blank,
        )
        logger.info(
            "low_confidence_evaluated",
            page_type=page_type,
            viewport=viewport,
            low_confidence=low_confidence,
            reasons=low_confidence_reasons,
        )
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Low confidence evaluated",
            details={"low_confidence": low_confidence, "reasons": low_confidence_reasons},
        )

        store_html = should_store_html(first_time, mode, low_confidence, error_summary)

        artifacts_saved: list[str] = []

        name = save_screenshot(
            repository, session_id, page_id, page_type, viewport, screenshot_bytes
        )
        if name:
            artifacts_saved.append(name)

        artifacts_saved.append(
            save_visible_text(
                repository, session_id, page_id, page_type, viewport, visible_text
            )
        )
        artifacts_saved.append(
            save_features_json(
                repository, session_id, page_id, page_type, viewport, features
            )
        )

        if store_html:
            html_content = await page.content()
            artifacts_saved.append(
                save_html_gz(
                    repository, session_id, page_id, page_type, viewport, html_content
                )
            )

        repository.update_page(
            page_id,
            status="ok",
            load_timings=load_timings,
            low_confidence_reasons=low_confidence_reasons,
        )

        success = True
        logger.info(
            "pdp_crawl_completed",
            viewport=viewport,
            artifacts_saved=artifacts_saved,
            low_confidence=low_confidence,
        )

    except Exception as e:
        error_summary = str(e)
        logger.error(
            "pdp_crawl_failed",
            error=str(e),
            error_type=type(e).__name__,
            viewport=viewport,
        )
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="error",
            message=f"PDP crawl failed: {str(e)}",
            details={"error": str(e), "error_type": type(e).__name__},
        )
        repository.update_page(page_id, status="failed", load_timings=load_timings)
        success = False

    finally:
        if page:
            await page.close()
        if context:
            await context.close()

    return success, {
        "page_id": page_id,
        "load_timings": load_timings,
        "error_summary": error_summary,
    }


async def crawl_pdp_async(
    pdp_url: str,
    session_id: UUID,
    repository: AuditRepository,
    mode: str,
    first_time: bool,
) -> dict:
    """
    Crawl PDP for desktop + mobile viewports.

    Returns dict with viewport results: {"desktop": {...}, "mobile": {...}}.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        results = {}
        for pt, viewport in PDP_VIEWPORTS:
            success, page_data = await crawl_pdp_viewport(
                browser,
                pdp_url,
                session_id,
                viewport,
                repository,
                mode,
                first_time,
            )
            results[viewport] = {"success": success, **page_data}
        await browser.close()
    return results


async def crawl_homepage_async(
    url: str,
    session_id: UUID,
    repository: AuditRepository,
    mode: str,
    first_time: bool,
) -> dict:
    """
    Async function to crawl homepage for both viewports.

    Returns dict with viewport results.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        results = {}
        for page_type, viewport in HOMEPAGE_VIEWPORTS:
            success, page_data = await crawl_homepage_viewport(
                browser,
                url,
                session_id,
                page_type,
                viewport,
                repository,
                mode,
                first_time,
            )
            results[viewport] = {"success": success, **page_data}

        await browser.close()

    return results
