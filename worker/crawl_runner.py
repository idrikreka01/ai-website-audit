"""
Crawl runner: homepage and PDP viewport crawls (Playwright, extraction, artifact persistence).

Encapsulates crawl_homepage_viewport, crawl_pdp_viewport, crawl_homepage_async, crawl_pdp_async.
No behavior change.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from playwright.async_api import Browser, async_playwright

from shared.config import get_config
from shared.logging import bind_request_context, get_logger
from worker.artifacts import (
    save_features_json,
    save_html_gz,
    save_screenshot,
    save_visible_text,
    should_store_html,
)
from worker.checkout_flow import run_checkout_flow
from worker.constants import HOMEPAGE_VIEWPORTS, PDP_VIEWPORTS
from worker.crawl import (
    CONSENT_POSITIONING_DELAY_MS,
    DEFAULT_VENDORS,
    MAX_PDP_CANDIDATES,
    POST_SCROLL_SETTLE_MS,
    add_preconsent_init_scripts,
    apply_preconsent_in_frames,
    create_browser_context,
    dismiss_popups,
    extract_features_json,
    extract_features_json_pdp,
    extract_pdp_candidate_links,
    navigate_with_retry,
    normalize_whitespace,
    run_extraction_retry_prep,
    run_overlay_hide_fallback,
    scroll_sequence,
    wait_for_page_ready,
)
from worker.error_summary import get_user_safe_error_summary
from worker.html_analysis import analyze_product_html
from worker.low_confidence import evaluate_low_confidence, evaluate_low_confidence_pdp
from worker.repository import AuditRepository

logger = get_logger(__name__)

# Transient Playwright errors that allow one extraction retry (TECH_SPEC §5 v1.24)
_EXTRACTION_RETRY_PHRASES = [
    ("Execution context was destroyed", "execution_context_destroyed"),
    ("Target closed", "target_closed"),
    ("Navigation interrupted", "navigation_interrupted"),
]


def _is_transient_extraction_error(exc: BaseException) -> bool:
    """True if the exception is a transient error that allows one extraction retry."""
    msg = str(exc)
    return any(phrase.lower() in msg.lower() for phrase, _ in _EXTRACTION_RETRY_PHRASES)


def _transient_extraction_reason(exc: BaseException) -> str:
    """Return the reason string for logging; use 'transient' if no known phrase matches."""
    msg = str(exc).lower()
    for phrase, reason in _EXTRACTION_RETRY_PHRASES:
        if phrase.lower() in msg:
            return reason
    return "transient"


def _log_popup_events(
    repository: AuditRepository,
    session_id: UUID,
    page_type: str,
    viewport: str,
    domain: str,
    events: list[dict],
    post_scroll: bool = False,
) -> None:
    """
    Write DB logs for each popup event with selector, action, result, attempt, and context.
    Failures are logged at warn level; non-fatal.
    """
    suffix = " (post-scroll)" if post_scroll else ""
    for ev in events:
        selector = ev.get("selector", "")
        action = ev.get("action", "")
        result = ev.get("result", "")
        attempt = ev.get("attempt", 0)
        level = "warn" if result == "failure" else "info"
        message = f"Popup {action} {result}{suffix}"
        details = {
            "selector": selector,
            "action": action,
            "result": result,
            "attempt": attempt,
            "page_type": page_type,
            "viewport": viewport,
            "domain": domain,
        }
        if ev.get("timestamp"):
            details["timestamp"] = ev["timestamp"]
        for key in ("hidden_count", "frame_count", "scroll_locked", "click_blocked", "current_url"):
            if key in ev:
                details[key] = ev[key]
        repository.create_log(
            session_id=session_id,
            level=level,
            event_type="popup",
            message=message,
            details=details,
        )


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
    domain = urlparse(url).netloc or ""
    bind_request_context(
        session_id=str(session_id),
        page_type=page_type,
        viewport=viewport,
        domain=domain,
    )

    logger.info("crawl_started", url=url, viewport=viewport, domain=domain)

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
        try:
            vendors = await add_preconsent_init_scripts(context, DEFAULT_VENDORS)
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="popup",
                message="Preconsent init scripts added",
                details={"vendors": vendors, "phase": "init"},
            )
        except Exception as e:
            logger.warning(
                "preconsent_init_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
        page = await context.new_page()
        page.on(
            "crash",
            lambda: logger.error(
                "page_crashed",
                page_type=page_type,
                viewport=viewport,
                domain=domain,
            ),
        )
        page.on(
            "close",
            lambda: logger.warning(
                "page_closed",
                page_type=page_type,
                viewport=viewport,
                domain=domain,
            ),
        )
        page.on(
            "crash",
            lambda: logger.error(
                "page_crashed",
                page_type=page_type,
                viewport=viewport,
                domain=domain,
            ),
        )
        page.on(
            "close",
            lambda: logger.warning(
                "page_closed",
                page_type=page_type,
                viewport=viewport,
                domain=domain,
            ),
        )

        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Navigating to URL",
            details={
                "url": url,
                "viewport": viewport,
                "page_type": page_type,
                "domain": domain,
            },
        )

        nav_result = await navigate_with_retry(
            page,
            url,
            session_id=session_id,
            repository=repository,
            page_type=page_type,
            viewport=viewport,
            domain=domain,
        )
        if not nav_result.success:
            error_summary = nav_result.error_summary or "Navigation failed"
            logger.error(
                "navigation.failed",
                error_summary=error_summary,
                url=url,
                viewport=viewport,
                domain=domain,
            )
            raise RuntimeError(error_summary)

        try:
            result = await apply_preconsent_in_frames(page, DEFAULT_VENDORS)
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="popup",
                message="Preconsent applied (post-nav)",
                details={
                    "vendors": result.get("applied_vendors", []),
                    "frame_count": result.get("frame_count", 0),
                    "phase": "post-nav",
                },
            )
        except Exception as e:
            logger.warning(
                "preconsent_post_nav_failed",
                error=str(e),
                error_type=type(e).__name__,
            )

        logger.info("page_ready_start", page_type=page_type, viewport=viewport, domain=domain)
        logger.info("page_ready_start", page_type=page_type, viewport=viewport, domain=domain)
        load_timings = await wait_for_page_ready(page, soft_timeout=10000)
        logger.info("page_ready_end", page_type=page_type, viewport=viewport, domain=domain)
        logger.info("page_ready_end", page_type=page_type, viewport=viewport, domain=domain)
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Page ready",
            details=load_timings,
        )

        await asyncio.sleep(CONSENT_POSITIONING_DELAY_MS / 1000)
        popup_events = await dismiss_popups(page)
        _log_popup_events(
            repository, session_id, page_type, viewport, domain, popup_events, post_scroll=False
        )
        success_count = sum(1 for e in popup_events if e.get("result") == "success")
        if success_count:
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="popup",
                message=f"Dismissed {success_count} popups",
                details={
                    "dismissed_count": success_count,
                    "page_type": page_type,
                    "viewport": viewport,
                    "domain": domain,
                },
            )

        await scroll_sequence(page)
        await asyncio.sleep(POST_SCROLL_SETTLE_MS / 1000)
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Scroll sequence completed",
        )

        # Pass 2: popup dismissal after scroll (TECH_SPEC §5 two-pass flow)
        popup_events_2 = await dismiss_popups(page)
        _log_popup_events(
            repository, session_id, page_type, viewport, domain, popup_events_2, post_scroll=True
        )
        success_count_2 = sum(1 for e in popup_events_2 if e.get("result") == "success")
        if success_count_2:
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="popup",
                message=f"Dismissed {success_count_2} popups (post-scroll)",
                details={
                    "dismissed_count": success_count_2,
                    "page_type": page_type,
                    "viewport": viewport,
                    "domain": domain,
                },
            )

        # Last-resort overlay hide fallback (TECH_SPEC §5 v1.23): only when page still blocked
        overlay_fallback_events = await run_overlay_hide_fallback(page)
        _log_popup_events(
            repository, session_id, page_type, viewport, domain, overlay_fallback_events
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

        extraction_attempt = 1
        while True:
            try:
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
                    logger.warning(
                        "screenshot_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                    )

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
                    repository,
                    session_id,
                    page_id,
                    page_type,
                    viewport,
                    domain,
                    screenshot_bytes,
                )
                if name:
                    artifacts_saved.append(name)

                artifacts_saved.append(
                    save_visible_text(
                        repository,
                        session_id,
                        page_id,
                        page_type,
                        viewport,
                        domain,
                        visible_text,
                    )
                )
                artifacts_saved.append(
                    save_features_json(
                        repository,
                        session_id,
                        page_id,
                        page_type,
                        viewport,
                        domain,
                        features,
                    )
                )

                html_content = None
                if store_html:
                    html_content = await page.content()
                    artifacts_saved.append(
                        save_html_gz(
                            repository,
                            session_id,
                            page_id,
                            page_type,
                            viewport,
                            domain,
                            html_content,
                        )
                    )

                if page_type == "pdp" and html_content:
                    analyze_product_html(
                        html_content,
                        session_id,
                        page_id,
                        page_type,
                        viewport,
                        domain,
                        repository,
                    )

                    try:
                        config = get_config()
                        artifacts_root = Path(config.artifacts_dir)
                        normalized_domain = (domain or "").strip().lower()
                        if normalized_domain.startswith("www."):
                            normalized_domain = normalized_domain[4:]
                        normalized_domain = normalized_domain or "unknown-domain"
                        root_name = f"{normalized_domain}__{session_id}"
                        json_path = artifacts_root / root_name / "pdp" / "html_analysis.json"

                        if json_path.exists():
                            with open(json_path, "r", encoding="utf-8") as f:
                                html_analysis_json = json.load(f)
                            html_analysis_json["_file_path"] = str(json_path.absolute())

                            logger.info(
                                "checkout_flow_starting",
                                session_id=str(session_id),
                                viewport=viewport,
                                domain=domain,
                            )

                            await run_checkout_flow(
                                page,
                                url,
                                html_analysis_json,
                                session_id,
                                viewport,
                                domain,
                                repository,
                            )
                            
                            from worker.orchestrator import _compute_and_store_page_coverage
                            try:
                                _compute_and_store_page_coverage(session_id, repository)
                            except Exception as coverage_error:
                                logger.warning(
                                    "page_coverage_after_checkout_failed",
                                    error=str(coverage_error),
                                    error_type=type(coverage_error).__name__,
                                    session_id=str(session_id),
                                )
                    except Exception as e:
                        logger.warning(
                            "checkout_flow_failed",
                            error=str(e),
                            error_type=type(e).__name__,
                            session_id=str(session_id),
                        )

                break
            except Exception as e:
                if not _is_transient_extraction_error(e) or extraction_attempt >= 2:
                    raise
                reason = _transient_extraction_reason(e)
                repository.create_log(
                    session_id=session_id,
                    level="info",
                    event_type="retry",
                    message="Extraction retry",
                    details={
                        "reason": reason,
                        "attempt": 2,
                        "page_type": page_type,
                        "viewport": viewport,
                        "domain": domain,
                    },
                )
                logger.info(
                    "extraction_retry",
                    reason=reason,
                    attempt=2,
                    page_type=page_type,
                    viewport=viewport,
                    session_id=str(session_id),
                    domain=domain,
                )
                popup_events_r, overlay_events_r = await run_extraction_retry_prep(page)
                _log_popup_events(
                    repository,
                    session_id,
                    page_type,
                    viewport,
                    domain,
                    popup_events_r,
                )
                _log_popup_events(
                    repository,
                    session_id,
                    page_type,
                    viewport,
                    domain,
                    overlay_events_r,
                )
                extraction_attempt += 1

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
        error_summary = get_user_safe_error_summary(e)
        logger.error(
            "crawl_failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="error",
            message="Crawl failed",
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
    domain = urlparse(pdp_url).netloc or ""
    bind_request_context(
        session_id=str(session_id),
        page_type=page_type,
        viewport=viewport,
        domain=domain,
    )

    logger.info(
        "pdp_crawl_started",
        url=pdp_url,
        viewport=viewport,
        session_id=str(session_id),
        domain=domain,
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
        try:
            vendors = await add_preconsent_init_scripts(context, DEFAULT_VENDORS)
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="popup",
                message="Preconsent init scripts added",
                details={"vendors": vendors, "phase": "init"},
            )
        except Exception as e:
            logger.warning(
                "preconsent_init_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
        page = await context.new_page()

        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Navigating to PDP",
            details={
                "url": pdp_url,
                "viewport": viewport,
                "page_type": "pdp",
                "domain": domain,
            },
        )
        nav_result = await navigate_with_retry(
            page,
            pdp_url,
            session_id=session_id,
            repository=repository,
            page_type="pdp",
            viewport=viewport,
            domain=domain,
        )
        if not nav_result.success:
            error_summary = nav_result.error_summary or "PDP navigation failed"
            logger.error(
                "navigation.failed",
                error_summary=error_summary,
                url=pdp_url,
                viewport=viewport,
                domain=domain,
            )
            raise RuntimeError(error_summary)

        try:
            result = await apply_preconsent_in_frames(page, DEFAULT_VENDORS)
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="popup",
                message="Preconsent applied (post-nav)",
                details={
                    "vendors": result.get("applied_vendors", []),
                    "frame_count": result.get("frame_count", 0),
                    "phase": "post-nav",
                },
            )
        except Exception as e:
            logger.warning(
                "preconsent_post_nav_failed",
                error=str(e),
                error_type=type(e).__name__,
            )

        load_timings = await wait_for_page_ready(page, soft_timeout=10000)
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Page ready",
            details=load_timings,
        )

        await asyncio.sleep(CONSENT_POSITIONING_DELAY_MS / 1000)
        popup_events = await dismiss_popups(page)
        _log_popup_events(
            repository, session_id, page_type, viewport, domain, popup_events, post_scroll=False
        )
        success_count = sum(1 for e in popup_events if e.get("result") == "success")
        if success_count:
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="popup",
                message=f"Dismissed {success_count} popups",
                details={
                    "dismissed_count": success_count,
                    "page_type": page_type,
                    "viewport": viewport,
                    "domain": domain,
                },
            )

        await scroll_sequence(page)
        await asyncio.sleep(POST_SCROLL_SETTLE_MS / 1000)
        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Scroll sequence completed",
        )

        # Pass 2: popup dismissal after scroll (TECH_SPEC §5 two-pass flow)
        popup_events_2 = await dismiss_popups(page)
        _log_popup_events(
            repository, session_id, page_type, viewport, domain, popup_events_2, post_scroll=True
        )
        success_count_2 = sum(1 for e in popup_events_2 if e.get("result") == "success")
        if success_count_2:
            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="popup",
                message=f"Dismissed {success_count_2} popups (post-scroll)",
                details={
                    "dismissed_count": success_count_2,
                    "page_type": page_type,
                    "viewport": viewport,
                    "domain": domain,
                },
            )

        # Last-resort overlay hide fallback (TECH_SPEC §5 v1.23): only when page still blocked
        overlay_fallback_events = await run_overlay_hide_fallback(page)
        _log_popup_events(
            repository, session_id, page_type, viewport, domain, overlay_fallback_events
        )

        extraction_attempt = 1
        while True:
            try:
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
                    logger.warning(
                        "screenshot_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                    )

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
                    details={
                        "low_confidence": low_confidence,
                        "reasons": low_confidence_reasons,
                    },
                )

                store_html = should_store_html(first_time, mode, low_confidence, error_summary)

                artifacts_saved = []

                name = save_screenshot(
                    repository,
                    session_id,
                    page_id,
                    page_type,
                    viewport,
                    domain,
                    screenshot_bytes,
                )
                if name:
                    artifacts_saved.append(name)

                artifacts_saved.append(
                    save_visible_text(
                        repository,
                        session_id,
                        page_id,
                        page_type,
                        viewport,
                        domain,
                        visible_text,
                    )
                )
                artifacts_saved.append(
                    save_features_json(
                        repository,
                        session_id,
                        page_id,
                        page_type,
                        viewport,
                        domain,
                        features,
                    )
                )

                html_content = None
                if store_html:
                    html_content = await page.content()
                    artifacts_saved.append(
                        save_html_gz(
                            repository,
                            session_id,
                            page_id,
                            page_type,
                            viewport,
                            domain,
                            html_content,
                        )
                    )

                if page_type == "pdp" and html_content:
                    analyze_product_html(
                        html_content,
                        session_id,
                        page_id,
                        page_type,
                        viewport,
                        domain,
                        repository,
                    )

                    try:
                        config = get_config()
                        artifacts_root = Path(config.artifacts_dir)
                        normalized_domain = (domain or "").strip().lower()
                        if normalized_domain.startswith("www."):
                            normalized_domain = normalized_domain[4:]
                        normalized_domain = normalized_domain or "unknown-domain"
                        root_name = f"{normalized_domain}__{session_id}"
                        json_path = artifacts_root / root_name / "pdp" / "html_analysis.json"

                        if json_path.exists():
                            with open(json_path, "r", encoding="utf-8") as f:
                                html_analysis_json = json.load(f)
                            html_analysis_json["_file_path"] = str(json_path.absolute())

                            logger.info(
                                "checkout_flow_starting",
                                session_id=str(session_id),
                                viewport=viewport,
                                domain=domain,
                            )

                            await run_checkout_flow(
                                page,
                                pdp_url,
                                html_analysis_json,
                                session_id,
                                viewport,
                                domain,
                                repository,
                            )
                    except Exception as e:
                        logger.warning(
                            "checkout_flow_failed",
                            error=str(e),
                            error_type=type(e).__name__,
                            session_id=str(session_id),
                        )

                break
            except Exception as e:
                if not _is_transient_extraction_error(e) or extraction_attempt >= 2:
                    raise
                reason = _transient_extraction_reason(e)
                repository.create_log(
                    session_id=session_id,
                    level="info",
                    event_type="retry",
                    message="Extraction retry",
                    details={
                        "reason": reason,
                        "attempt": 2,
                        "page_type": page_type,
                        "viewport": viewport,
                        "domain": domain,
                    },
                )
                logger.info(
                    "extraction_retry",
                    reason=reason,
                    attempt=2,
                    page_type=page_type,
                    viewport=viewport,
                    session_id=str(session_id),
                    domain=domain,
                )
                popup_events_r, overlay_events_r = await run_extraction_retry_prep(page)
                _log_popup_events(
                    repository,
                    session_id,
                    page_type,
                    viewport,
                    domain,
                    popup_events_r,
                )
                _log_popup_events(
                    repository,
                    session_id,
                    page_type,
                    viewport,
                    domain,
                    overlay_events_r,
                )
                extraction_attempt += 1

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
        error_summary = get_user_safe_error_summary(e)
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
            message="PDP crawl failed",
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
