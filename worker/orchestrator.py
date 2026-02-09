"""
Session orchestrator: full flow from homepage crawl → PDP discovery → PDP crawl → status rollup.

Owns the full session flow; no DB session opening (jobs.py does that).
No behavior change.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse
from uuid import UUID

from shared.logging import bind_request_context, get_logger
from worker.crawl_runner import crawl_homepage_async, crawl_pdp_async
from worker.pdp_discovery import ensure_pdp_page_records, run_pdp_discovery_and_validation
from worker.repository import AuditRepository
from worker.session_status import compute_session_status, session_low_confidence_from_pages

logger = get_logger(__name__)


def run_audit_session(url: str, session_uuid: UUID, repository: AuditRepository) -> None:
    """
    Run full audit session: homepage crawl, PDP discovery, PDP crawl, status rollup.

    Assumes session exists and DB session is open. Raises on error; jobs.py catches
    and updates status.
    """
    session_data = repository.get_session_by_id(session_uuid)
    if session_data is None:
        logger.error(
            "audit_session_not_found",
            session_id=str(session_uuid),
            error_type="ValueError",
        )
        raise ValueError(f"Audit session {session_uuid} not found")

    mode = session_data["mode"]
    first_time = not repository.has_prior_sessions(url, exclude_session_id=session_uuid)
    session_id_str = str(session_uuid)
    domain = urlparse(url).netloc

    bind_request_context(session_id=session_id_str, domain=domain)

    logger.info(
        "first_time_check",
        first_time=first_time,
        url=url,
        session_id=session_id_str,
    )

    repository.create_log(
        session_id=session_uuid,
        level="info",
        event_type="navigation",
        message="Audit job started",
        details={"url": url, "first_time": first_time},
    )

    repository.update_session_status(session_uuid, "running")
    logger.info("audit_session_status_updated", status="running")

    from shared.config import get_config
    config = get_config()
    if config.telegram_bot_token and config.telegram_chat_id:
        try:
            from shared.telegram import send_telegram_message
            message = f"""🚀 <b>Audit Started</b>

🌐 <b>URL:</b> {url}
🆔 <b>Session:</b> {session_id_str[:8]}...
📊 <b>Mode:</b> {mode}

⏳ Starting crawl..."""
            send_telegram_message(
                bot_token=config.telegram_bot_token,
                chat_id=config.telegram_chat_id,
                message=message,
                parse_mode="HTML",
            )
            logger.info("telegram_audit_started_notification_sent", session_id=session_id_str)
        except Exception as e:
            logger.warning("telegram_audit_started_notification_failed", error=str(e), session_id=session_id_str)

    repository.create_log(
        session_id=session_uuid,
        level="info",
        event_type="navigation",
        message="Session status updated to running",
        details={"status": "running"},
    )

    results = asyncio.run(crawl_homepage_async(url, session_uuid, repository, mode, first_time))

    pdp_candidate_urls = results.get("desktop", {}).get("pdp_candidate_urls", [])
    repository.create_log(
        session_id=session_uuid,
        level="info",
        event_type="navigation",
        message="PDP candidate links extracted",
        details={"count": len(pdp_candidate_urls), "sample": pdp_candidate_urls[:5]},
    )

    ensure_pdp_page_records(session_uuid, repository)

    pdp_url: str | None = asyncio.run(
        run_pdp_discovery_and_validation(pdp_candidate_urls, url, session_uuid, repository)
    )
    repository.update_session_pdp_url(session_uuid, pdp_url)

    if pdp_url:
        repository.create_log(
            session_id=session_uuid,
            level="info",
            event_type="navigation",
            message="PDP selected",
            details={"pdp_url": pdp_url},
        )
        for page in repository.get_pages_by_session_id(session_uuid):
            if page["page_type"] == "pdp":
                repository.update_page(page["id"], status="pending")
    else:
        repository.create_log(
            session_id=session_uuid,
            level="info",
            event_type="navigation",
            message="PDP not found",
            details={"reason": "no_valid_candidate"},
        )
        for page in repository.get_pages_by_session_id(session_uuid):
            if page["page_type"] == "pdp":
                repository.update_page(
                    page["id"],
                    status="failed",
                    load_timings={"pdp_not_found": True},
                )

    results_pdp: dict = {}
    if pdp_url:
        results_pdp = asyncio.run(
            crawl_pdp_async(pdp_url, session_uuid, repository, mode, first_time)
        )

    home_desktop = results.get("desktop", {}).get("success", False)
    home_mobile = results.get("mobile", {}).get("success", False)
    pdp_desktop = results_pdp.get("desktop", {}).get("success", False) if pdp_url else False
    pdp_mobile = results_pdp.get("mobile", {}).get("success", False) if pdp_url else False

    final_status, error_summary = compute_session_status(
        home_desktop, home_mobile, pdp_desktop, pdp_mobile, pdp_url
    )

    repository.update_session_status(session_uuid, final_status, error_summary=error_summary)
    logger.info("audit_session_status_updated", status=final_status)

    pages = repository.get_pages_by_session_id(session_uuid)
    session_low_confidence = session_low_confidence_from_pages(pages)

    if session_low_confidence:
        repository.update_session_low_confidence(session_uuid, True)
        logger.info(
            "low_confidence_rolled_up",
            session_id=session_id_str,
            reason="page_has_low_confidence_reasons",
        )
        repository.create_log(
            session_id=session_uuid,
            level="info",
            event_type="navigation",
            message="Session low_confidence set to true",
            details={"reason": "page_has_low_confidence_reasons"},
        )

    repository.create_log(
        session_id=session_uuid,
        level="info",
        event_type="navigation",
        message=f"Session status updated to {final_status}",
        details={
            "status": final_status,
            "home_desktop": home_desktop,
            "home_mobile": home_mobile,
            "pdp_desktop": pdp_desktop,
            "pdp_mobile": pdp_mobile,
            "low_confidence": session_low_confidence,
            "pdp_url": pdp_url,
        },
    )
