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


def _discover_page_types_from_artifacts(session_id_str: str, artifacts_dir: str = "./artifacts") -> list[str]:
    """
    Discover available page types by checking artifact directories.
    
    Args:
        session_id_str: Session identifier (format: domain__uuid)
        artifacts_dir: Base artifacts directory
        
    Returns:
        List of page types that have both desktop and mobile artifacts
    """
    from pathlib import Path
    
    artifacts_path = Path(artifacts_dir) / session_id_str
    if not artifacts_path.exists():
        return []
    
    available_page_types = []
    valid_page_types = ["homepage", "pdp", "cart", "checkout"]
    
    for page_type in valid_page_types:
        page_type_path = artifacts_path / page_type
        if not page_type_path.exists() or not page_type_path.is_dir():
            continue
        
        desktop_path = page_type_path / "desktop"
        mobile_path = page_type_path / "mobile"
        
        desktop_visible_text = (desktop_path / "visible_text.txt").exists()
        desktop_features = (desktop_path / "features_json.json").exists()
        desktop_has_artifacts = desktop_path.exists() and (desktop_visible_text or desktop_features)
        
        mobile_visible_text = (mobile_path / "visible_text.txt").exists()
        mobile_features = (mobile_path / "features_json.json").exists()
        mobile_has_artifacts = mobile_path.exists() and (mobile_visible_text or mobile_features)
        
        if desktop_has_artifacts and mobile_has_artifacts:
            available_page_types.append(page_type)
    
    return available_page_types


def _run_audit_evaluation_for_page_types(
    session_uuid: UUID,
    domain: str,
    repository: AuditRepository,
    page_types: list[str] = None,
) -> None:
    """
    Run audit evaluation for page types. If page_types is None, auto-discover from artifacts.
    
    Args:
        session_uuid: Session UUID
        domain: Domain name
        repository: Audit repository
        page_types: Optional list of page types to evaluate. If None, discovers from artifacts.
    """
    from get_questions_by_page_type import get_questions_by_page_type
    from audit_evaluator import AuditEvaluator
    
    normalized_domain = (domain or "").strip().lower()
    if normalized_domain.startswith("www."):
        normalized_domain = normalized_domain[4:]
    normalized_domain = normalized_domain or "unknown-domain"
    session_id_str = f"{normalized_domain}__{session_uuid}"
    
    if page_types is None:
        page_types = _discover_page_types_from_artifacts(session_id_str)
        logger.info(
            "audit_evaluation_page_types_discovered",
            page_types=page_types,
            session_id=str(session_uuid),
        )
    
    if not page_types:
        logger.info(
            "audit_evaluation_skipped",
            reason="no_page_types_found",
            session_id=str(session_uuid),
        )
        return
    
    for page_type in page_types:
        from pathlib import Path
        from shared.config import get_config
        
        config = get_config()
        artifacts_path = Path(config.artifacts_dir) / session_id_str / page_type
        
        desktop_path = artifacts_path / "desktop"
        mobile_path = artifacts_path / "mobile"
        
        desktop_visible_text = (desktop_path / "visible_text.txt").exists()
        desktop_features = (desktop_path / "features_json.json").exists()
        desktop_has_artifacts = desktop_path.exists() and (desktop_visible_text or desktop_features)
        
        mobile_visible_text = (mobile_path / "visible_text.txt").exists()
        mobile_features = (mobile_path / "features_json.json").exists()
        mobile_has_artifacts = mobile_path.exists() and (mobile_visible_text or mobile_features)
        
        if not (desktop_has_artifacts and mobile_has_artifacts):
            logger.info(
                "audit_evaluation_skipped",
                page_type=page_type,
                reason="missing_artifacts",
                desktop_exists=desktop_has_artifacts,
                mobile_exists=mobile_has_artifacts,
                session_id=str(session_uuid),
            )
            continue
        
        try:
            logger.info(
                "audit_evaluation_starting",
                page_type=page_type,
                session_id=str(session_uuid),
            )
            
            normalized_page_type = "product" if page_type == "pdp" else page_type
            questions = get_questions_by_page_type(normalized_page_type)
            if not questions.get("question"):
                logger.warning(
                    "audit_evaluation_skipped",
                    page_type=page_type,
                    reason="no_questions_found",
                    session_id=str(session_uuid),
                )
                continue
            
            evaluator = AuditEvaluator(artifacts_dir="./artifacts")
            results = evaluator.run_audit(
                session_id=session_id_str,
                page_type=normalized_page_type,
                questions=questions.get("question", {}),
                chunk_size=30000,
                save_response=True,
                include_screenshots=False,
                repository=repository,
            )
            
            logger.info(
                "audit_evaluation_completed",
                page_type=page_type,
                results_count=len(results),
                session_id=str(session_uuid),
            )
            
            repository.create_log(
                session_id=session_uuid,
                level="info",
                event_type="artifact",
                message=f"Audit evaluation completed for {page_type}",
                details={
                    "page_type": page_type,
                    "results_count": len(results),
                    "pass_count": sum(1 for r in results.values() if r.get("result") == "PASS"),
                    "fail_count": sum(1 for r in results.values() if r.get("result") == "FAIL"),
                },
            )
            
        except Exception as e:
            logger.error(
                "audit_evaluation_failed",
                page_type=page_type,
                error=str(e),
                error_type=type(e).__name__,
                session_id=str(session_uuid),
            )
            repository.create_log(
                session_id=session_uuid,
                level="error",
                event_type="error",
                message=f"Audit evaluation failed for {page_type}",
                details={
                    "page_type": page_type,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )


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
            logger.warning(
                "telegram_audit_started_notification_failed",
                error=str(e),
                session_id=session_id_str,
            )

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

    _run_audit_evaluation_for_page_types(session_uuid, domain, repository, page_types=None)
