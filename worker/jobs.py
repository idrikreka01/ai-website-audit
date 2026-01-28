"""
RQ job handlers for audit processing.

This module contains the job handler that processes audit sessions with
Playwright-based homepage evidence capture.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from playwright.async_api import async_playwright, Browser, TimeoutError as PlaywrightTimeoutError
from urllib.parse import urlparse

from worker.crawl import (
    create_browser_context,
    wait_for_page_ready,
    scroll_sequence,
    dismiss_popups,
    extract_features_json,
    normalize_whitespace,
)
from worker.db import get_db_session
from worker.low_confidence import evaluate_low_confidence
from worker.repository import AuditRepository
from worker.storage import (
    build_artifact_path,
    write_screenshot,
    write_text,
    write_json,
    write_html_gz,
    get_storage_uri,
)
from shared.config import get_config
from shared.logging import bind_request_context, get_logger


logger = get_logger(__name__)

# Homepage viewports only (no PDP in this task)
HOMEPAGE_VIEWPORTS = [
    ("homepage", "desktop"),
    ("homepage", "mobile"),
]


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

    # Get or create page record
    page_data = repository.get_page_by_session_type_viewport(
        session_id, page_type, viewport
    )
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

    try:
        # Create browser context
        context = await create_browser_context(browser, viewport)
        page = await context.new_page()

        # Navigate
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message=f"Navigating to {url}",
            details={"url": url, "viewport": viewport},
        )

        try:
            # Hard timeout: 30 seconds
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            final_url = page.url
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

        # Wait for page ready
        load_timings = await wait_for_page_ready(page, soft_timeout=10000)
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Page ready",
            details=load_timings,
        )

        # Dismiss popups
        dismissed = await dismiss_popups(page)
        if dismissed:
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="popup",
                message=f"Dismissed {len(dismissed)} popups",
                details={"dismissed": dismissed},
            )

        # Scroll sequence
        await scroll_sequence(page)
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Scroll sequence completed",
        )

        # Extract visible text
        visible_text = await page.inner_text("body")
        visible_text = normalize_whitespace(visible_text)
        text_length = len(visible_text)

        # Extract features JSON
        features = await extract_features_json(page)
        has_h1 = len(features["headings"]["h1"]) > 0
        has_primary_cta = len(features["ctas"]) > 0

        # Capture screenshot
        try:
            screenshot_bytes = await page.screenshot(type="png", full_page=True)
            screenshot_failed = False
            screenshot_blank = len(screenshot_bytes) < 1000  # Heuristic for blank
        except Exception as e:
            screenshot_bytes = None
            screenshot_failed = True
            logger.warning("screenshot_failed", error=str(e))

        # Evaluate low confidence
        low_confidence, low_confidence_reasons = evaluate_low_confidence(
            has_h1=has_h1,
            has_primary_cta=has_primary_cta,
            visible_text_length=text_length,
            screenshot_failed=screenshot_failed,
            screenshot_blank=screenshot_blank,
        )

        # Determine if HTML should be stored (conditional rules)
        # Store html.gz when: first_time OR debug/evidence_pack OR low_confidence OR failure
        store_html = (
            first_time
            or mode in ("debug", "evidence_pack")
            or low_confidence
            or error_summary is not None
        )
        
        if store_html:
            logger.info(
                "html_storage_triggered",
                first_time=first_time,
                mode=mode,
                low_confidence=low_confidence,
                has_error=error_summary is not None,
            )

        # Save artifacts
        artifacts_saved = []

        # Screenshot
        if screenshot_bytes:
            screenshot_path = build_artifact_path(
                session_id, page_type, viewport, "screenshot"
            )
            size, checksum = write_screenshot(screenshot_path, screenshot_bytes)
            storage_uri = get_storage_uri(screenshot_path)
            repository.create_artifact(
                session_id=session_id,
                page_id=page_id,
                artifact_type="screenshot",
                storage_uri=storage_uri,
                size_bytes=size,
                checksum=checksum,
            )
            artifacts_saved.append("screenshot")
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="artifact",
                message="Screenshot saved",
                details={"size_bytes": size, "storage_uri": storage_uri},
            )

        # Visible text
        text_path = build_artifact_path(
            session_id, page_type, viewport, "visible_text"
        )
        size, checksum = write_text(text_path, visible_text)
        storage_uri = get_storage_uri(text_path)
        repository.create_artifact(
            session_id=session_id,
            page_id=page_id,
            artifact_type="visible_text",
            storage_uri=storage_uri,
            size_bytes=size,
            checksum=checksum,
        )
        artifacts_saved.append("visible_text")
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="artifact",
            message="Visible text saved",
            details={"size_bytes": size, "storage_uri": storage_uri},
        )

        # Features JSON
        features_path = build_artifact_path(
            session_id, page_type, viewport, "features_json"
        )
        size, checksum = write_json(features_path, features)
        storage_uri = get_storage_uri(features_path)
        repository.create_artifact(
            session_id=session_id,
            page_id=page_id,
            artifact_type="features_json",
            storage_uri=storage_uri,
            size_bytes=size,
            checksum=checksum,
        )
        artifacts_saved.append("features_json")
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="artifact",
            message="Features JSON saved",
            details={"size_bytes": size, "storage_uri": storage_uri},
        )

        # HTML (conditional)
        if store_html:
            html_content = await page.content()
            html_path = build_artifact_path(
                session_id, page_type, viewport, "html_gz"
            )
            size, checksum = write_html_gz(html_path, html_content)
            storage_uri = get_storage_uri(html_path)
            # TODO: Set retention_until based on retention policy
            repository.create_artifact(
                session_id=session_id,
                page_id=page_id,
                artifact_type="html_gz",
                storage_uri=storage_uri,
                size_bytes=size,
                checksum=checksum,
            )
            artifacts_saved.append("html_gz")
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="artifact",
                message="HTML (gzip) saved",
                details={"size_bytes": size, "storage_uri": storage_uri},
            )

        # Update page record
        # Note: low_confidence is derived from low_confidence_reasons (non-empty = low confidence)
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

    return success, {
        "page_id": page_id,
        "load_timings": load_timings,
        "error_summary": error_summary,
    }


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


def process_audit_job(session_id: str, url: str) -> None:
    """
    RQ job handler to process an audit session with homepage crawling.

    Args:
        session_id: The audit session UUID as a string
        url: The normalized URL to audit
    """
    session_uuid = UUID(session_id)

    # Bind logging context
    domain = urlparse(url).netloc
    bind_request_context(session_id=session_id, domain=domain)

    logger.info("audit_job_started", url=url)

    with get_db_session() as db_session:
        repository = AuditRepository(db_session)

        # Load session
        session_data = repository.get_session_by_id(session_uuid)
        if session_data is None:
            logger.error("audit_session_not_found", session_id=session_id)
            raise ValueError(f"Audit session {session_id} not found")

        mode = session_data["mode"]

        # Check if this is a first-time crawl (no prior sessions for same domain/URL)
        first_time = not repository.has_prior_sessions(url, exclude_session_id=session_uuid)
        logger.info(
            "first_time_check",
            first_time=first_time,
            url=url,
            session_id=session_id,
        )

        # Log job start
        repository.create_log(
            session_id=session_uuid,
            level="info",
            event_type="navigation",
            message="Audit job started",
            details={"url": url, "first_time": first_time},
        )

        # Update status to "running"
        repository.update_session_status(session_uuid, "running")
        logger.info("audit_session_status_updated", status="running")

        repository.create_log(
            session_id=session_uuid,
            level="info",
            event_type="navigation",
            message="Session status updated to running",
            details={"status": "running"},
        )

        # Crawl homepage for both viewports
        try:
            results = asyncio.run(
                crawl_homepage_async(url, session_uuid, repository, mode, first_time)
            )

            # Determine session status
            desktop_success = results.get("desktop", {}).get("success", False)
            mobile_success = results.get("mobile", {}).get("success", False)

            error_summary = None
            if desktop_success and mobile_success:
                final_status = "completed"
            elif desktop_success or mobile_success:
                final_status = "partial"
                error_summary = "One or more viewports failed"
            else:
                final_status = "failed"
                error_summary = "All viewports failed"

            repository.update_session_status(
                session_uuid, final_status, error_summary=error_summary
            )
            logger.info("audit_session_status_updated", status=final_status)

            # Roll up low_confidence: set session.low_confidence = true if any homepage viewport has low_confidence_reasons
            pages = repository.get_pages_by_session_id(session_uuid)
            session_low_confidence = False
            for page in pages:
                # Only check homepage viewports (per task requirement)
                if page["page_type"] == "homepage":
                    low_confidence_reasons = page.get("low_confidence_reasons", [])
                    if low_confidence_reasons and len(low_confidence_reasons) > 0:
                        session_low_confidence = True
                        break

            if session_low_confidence:
                repository.update_session_low_confidence(session_uuid, True)
                logger.info(
                    "low_confidence_rolled_up",
                    session_id=session_id,
                    reason="homepage_viewport_has_low_confidence_reasons",
                )
                repository.create_log(
                    session_id=session_uuid,
                    level="info",
                    event_type="navigation",
                    message="Session low_confidence set to true",
                    details={
                        "reason": "homepage_viewport_has_low_confidence_reasons",
                    },
                )

            repository.create_log(
                session_id=session_uuid,
                level="info",
                event_type="navigation",
                message=f"Session status updated to {final_status}",
                details={
                    "status": final_status,
                    "desktop_success": desktop_success,
                    "mobile_success": mobile_success,
                    "low_confidence": session_low_confidence,
                },
            )

        except Exception as e:
            logger.error("audit_job_error", error=str(e), error_type=type(e).__name__)
            repository.update_session_status(
                session_uuid, "failed", error_summary=str(e)
            )
            repository.create_log(
                session_id=session_uuid,
                level="error",
                event_type="error",
                message=f"Audit job failed: {str(e)}",
                details={"error": str(e), "error_type": type(e).__name__},
            )
            raise

        logger.info("audit_job_completed", session_id=session_id)
