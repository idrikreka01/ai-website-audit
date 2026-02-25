"""
Session orchestrator: full flow from homepage crawl → PDP discovery → PDP crawl → status rollup.

Owns the full session flow; no DB session opening (jobs.py does that).
No behavior change.
"""

from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

from shared.config import get_config
from shared.logging import bind_request_context, get_logger
from shared.telegram import send_telegram_message
from worker.crawl_runner import crawl_homepage_async, crawl_pdp_async
from worker.pdp_discovery import ensure_pdp_page_records, run_pdp_discovery_and_validation
from worker.pdf_generator import generate_and_save_pdf_report
from worker.repository import AuditRepository
from worker.session_status import compute_session_status, session_low_confidence_from_pages

logger = get_logger(__name__)


def compute_ai_audit_score(
    session_uuid: UUID, domain: str, repository: AuditRepository
) -> Optional[dict]:
    """
    Compute AI audit score (0.0-1.0) and flag ('high', 'medium', 'low') from audit_results.

    Args:
        session_uuid: Session UUID
        domain: Domain name
        repository: Audit repository

    Returns:
        Dict with score (0-1), flag ('high'/'medium'/'low'), or None if no results
    """
    normalized_domain = (domain or "").strip().lower()
    if normalized_domain.startswith("www."):
        normalized_domain = normalized_domain[4:]
    normalized_domain = normalized_domain or "unknown-domain"
    session_id_str = f"{normalized_domain}__{session_uuid}"

    audit_results = repository.get_audit_results_by_session_id(session_id_str)
    if not audit_results:
        logger.info(
            "ai_audit_score_skipped",
            reason="no_audit_results",
            session_id=str(session_uuid),
        )
        return None

    total_weight = 0.0
    weighted_pass = 0.0
    unknown_count = 0

    for result in audit_results:
        result_value = (result.get("result") or "").lower()
        if result_value == "unknown":
            unknown_count += 1
            continue
        confidence = result.get("confidence_score", 0.5)
        if confidence <= 0:
            confidence = 0.5
        passed = result_value == "pass"
        total_weight += confidence
        if passed:
            weighted_pass += confidence

    if total_weight == 0:
        logger.warning(
            "ai_audit_score_zero_weight",
            session_id=str(session_uuid),
        )
        return None

    score = weighted_pass / total_weight

    if score >= 0.8:
        flag = "high"
    elif score >= 0.5:
        flag = "medium"
    else:
        flag = "low"

    pass_count = sum(1 for r in audit_results if (r.get("result") or "").lower() == "pass")
    fail_count = sum(1 for r in audit_results if (r.get("result") or "").lower() == "fail")
    logger.info(
        "ai_audit_score_computed",
        session_id=str(session_uuid),
        score=score,
        flag=flag,
        total_results=len(audit_results),
        pass_count=pass_count,
        fail_count=fail_count,
        unknown_count=unknown_count,
        weighted_pass=weighted_pass,
        total_weight=total_weight,
    )

    return {
        "score": round(score, 4),
        "flag": flag,
    }


def compute_functional_flow_score(checkout_result: dict) -> int:
    """
    Compute functional flow score (0-3) from checkout result.

    Args:
        checkout_result: Dict from run_checkout_flow() (add_to_cart, cart_nav, checkout_nav)

    Returns:
        Score 0-3: +1 per completed step (add_to_cart, cart_navigation, checkout_navigation)
    """
    score = 0
    if checkout_result.get("add_to_cart", {}).get("status") == "completed":
        score += 1
    if checkout_result.get("cart_navigation", {}).get("status") == "completed":
        score += 1
    if checkout_result.get("checkout_navigation", {}).get("status") == "completed":
        score += 1
    return score


def compute_overall_audit_score(session_uuid: UUID, repository: AuditRepository) -> dict:
    """
    Compute overall audit performance percentage from all 3 flags.

    Returns dict with:
    - overall_percentage: float (0-100)
    - flag1_percentage: float (Page Coverage, 0-100)
    - flag2_percentage: float (AI Audit, 0-100 or None if not available)
    - flag3_percentage: float (Functional Flow, 0-100)
    - needs_manual_review: bool (True if < 70%)
    """
    session_data = repository.get_session_by_id(session_uuid)
    if not session_data:
        logger.warning(
            "session_not_found_for_scoring",
            session_id=str(session_uuid),
        )
        return {
            "overall_percentage": 0.0,
            "flag1_percentage": 0.0,
            "flag2_percentage": None,
            "flag3_percentage": 0.0,
            "needs_manual_review": True,
        }

    flag1_score = session_data.get("page_coverage_score", 0)
    flag1_percentage = (flag1_score / 4.0) * 100.0

    flag2_score = session_data.get("ai_audit_score")
    flag2_percentage = None
    if flag2_score is not None:
        flag2_percentage = flag2_score * 100.0

    flag3_score = session_data.get("functional_flow_score", 0)
    flag3_percentage = (flag3_score / 3.0) * 100.0

    percentages = [flag1_percentage, flag3_percentage]
    if flag2_percentage is not None:
        percentages.append(flag2_percentage)

    overall_percentage = sum(percentages) / len(percentages)
    needs_manual_review = overall_percentage < 70.0

    result = {
        "overall_percentage": round(overall_percentage, 2),
        "flag1_percentage": round(flag1_percentage, 2),
        "flag2_percentage": round(flag2_percentage, 2) if flag2_percentage is not None else None,
        "flag3_percentage": round(flag3_percentage, 2),
        "needs_manual_review": needs_manual_review,
    }

    logger.info(
        "overall_audit_score_computed",
        session_id=str(session_uuid),
        overall_percentage=result["overall_percentage"],
        flag1_percentage=result["flag1_percentage"],
        flag2_percentage=result["flag2_percentage"],
        flag3_percentage=result["flag3_percentage"],
        needs_manual_review=needs_manual_review,
    )

    return result


def send_manual_review_notification(
    session_uuid: UUID, score_data: dict, url: str, reason: Optional[str] = None
) -> None:
    """
    Send Telegram notification for manual review when score < 70% or page coverage < 4.
    """
    config = get_config()
    if not config.telegram_bot_token or not config.telegram_chat_id:
        logger.warning(
            "telegram_not_configured_for_manual_review",
            session_id=str(session_uuid),
        )
        return

    reason_text = reason or "Overall score < 70%"
    flag2_pct = (
        f"{score_data['flag2_percentage']}%"
        if score_data.get("flag2_percentage") is not None
        else "(not available)"
    )
    message = f"""🚨 <b>Manual Review Required</b>

Session: <code>{session_uuid}</code>
URL: {url}

<b>Overall Score: {score_data["overall_percentage"]}%</b>

Flag Breakdown:
• Page Coverage: {score_data["flag1_percentage"]}%
• AI Audit: {flag2_pct}
• Functional Flow: {score_data["flag3_percentage"]}%

Status: Needs manual review
Reason: {reason_text}"""

    success = send_telegram_message(
        bot_token=config.telegram_bot_token,
        chat_id=config.telegram_chat_id,
        message=message,
        parse_mode="HTML",
    )

    if success:
        logger.info(
            "manual_review_notification_sent",
            session_id=str(session_uuid),
            overall_percentage=score_data["overall_percentage"],
        )
    else:
        logger.warning(
            "manual_review_notification_failed",
            session_id=str(session_uuid),
        )


def _compute_and_store_page_coverage(session_uuid: UUID, repository: AuditRepository) -> None:
    """
    Compute page coverage flags by checking audit_pages table for both desktop and mobile.

    Args:
        session_uuid: Session UUID
        repository: Audit repository
    """
    pages = repository.get_pages_by_session_id(session_uuid)

    page_type_viewports = {}
    for page in pages:
        page_type = page["page_type"]
        viewport = page["viewport"]
        status = page["status"]

        if page_type not in page_type_viewports:
            page_type_viewports[page_type] = {"desktop": False, "mobile": False}

        if status == "ok":
            page_type_viewports[page_type][viewport] = True

    homepage_ok = page_type_viewports.get("homepage", {}).get(
        "desktop", False
    ) and page_type_viewports.get("homepage", {}).get("mobile", False)
    pdp_ok = page_type_viewports.get("pdp", {}).get("desktop", False) and page_type_viewports.get(
        "pdp", {}
    ).get("mobile", False)
    cart_ok = page_type_viewports.get("cart", {}).get("desktop", False) and page_type_viewports.get(
        "cart", {}
    ).get("mobile", False)
    checkout_ok = page_type_viewports.get("checkout", {}).get(
        "desktop", False
    ) and page_type_viewports.get("checkout", {}).get("mobile", False)

    page_coverage_score = sum([homepage_ok, pdp_ok, cart_ok, checkout_ok])

    repository.update_session_page_coverage(
        session_id=session_uuid,
        homepage_ok=homepage_ok,
        pdp_ok=pdp_ok,
        cart_ok=cart_ok,
        checkout_ok=checkout_ok,
        page_coverage_score=page_coverage_score,
    )

    logger.info(
        "page_coverage_computed",
        session_id=str(session_uuid),
        homepage_ok=homepage_ok,
        pdp_ok=pdp_ok,
        cart_ok=cart_ok,
        checkout_ok=checkout_ok,
        page_coverage_score=page_coverage_score,
    )


def _discover_page_types_from_artifacts(
    session_id_str: str, artifacts_dir: str = "./artifacts"
) -> list[str]:
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
    from audit_evaluator import AuditEvaluator
    from get_questions_by_page_type import get_questions_by_page_type

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
                    "pass_count": sum(
                        1 for r in results.values() if (r.get("result") or "").lower() == "pass"
                    ),
                    "fail_count": sum(
                        1 for r in results.values() if (r.get("result") or "").lower() == "fail"
                    ),
                    "unknown_count": sum(
                        1 for r in results.values() if (r.get("result") or "").lower() == "unknown"
                    ),
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

    try:
        _compute_and_store_page_coverage(session_uuid, repository)
    except Exception as e:
        logger.error(
            "page_coverage_computation_failed",
            error=str(e),
            error_type=type(e).__name__,
            session_id=str(session_uuid),
            stage="after_homepage",
        )

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
    checkout_result: Optional[dict] = None
    if pdp_url:
        results_pdp = asyncio.run(
            crawl_pdp_async(pdp_url, session_uuid, repository, mode, first_time)
        )

        for viewport in ["desktop", "mobile"]:
            viewport_data = results_pdp.get(viewport, {})
            logger.info(
                "checking_viewport_for_checkout_result",
                session_id=str(session_uuid),
                viewport=viewport,
                has_checkout_result="checkout_result" in viewport_data,
                viewport_keys=list(viewport_data.keys()),
            )
            if "checkout_result" in viewport_data:
                checkout_result = viewport_data["checkout_result"]
                logger.info(
                    "checkout_result_found",
                    session_id=str(session_uuid),
                    viewport=viewport,
                    checkout_result_keys=(
                        list(checkout_result.keys()) if isinstance(checkout_result, dict) else None
                    ),
                )
                break

        if checkout_result:
            try:
                score = compute_functional_flow_score(checkout_result)
                repository.update_session_functional_flow(
                    session_id=session_uuid,
                    functional_flow_score=score,
                    functional_flow_details=checkout_result,
                )
                logger.info(
                    "functional_flow_score_computed",
                    session_id=str(session_uuid),
                    functional_flow_score=score,
                )
            except Exception as e:
                logger.error(
                    "functional_flow_score_computation_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    session_id=str(session_uuid),
                )

        try:
            _compute_and_store_page_coverage(session_uuid, repository)
        except Exception as e:
            logger.error(
                "page_coverage_computation_failed",
                error=str(e),
                error_type=type(e).__name__,
                session_id=str(session_uuid),
                stage="after_pdp",
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

    try:
        _compute_and_store_page_coverage(session_uuid, repository)
    except Exception as e:
        logger.error(
            "page_coverage_computation_failed",
            error=str(e),
            error_type=type(e).__name__,
            session_id=str(session_uuid),
            stage="before_audit_check",
        )

    session_data_after_coverage = repository.get_session_by_id(session_uuid)
    page_coverage_score = (
        session_data_after_coverage.get("page_coverage_score", 0)
        if session_data_after_coverage
        else 0
    )

    if page_coverage_score < 4:
        logger.warning(
            "audit_process_stopped_low_page_coverage",
            session_id=str(session_uuid),
            page_coverage_score=page_coverage_score,
            reason="Page coverage < 4, stopping audit evaluation and score computation.",
        )
        repository.update_session_status(
            session_uuid,
            "partial",
            error_summary=f"Page coverage {page_coverage_score}/4 below threshold.",
        )
        try:
            repository.update_session_overall_score(
                session_id=session_uuid,
                overall_score_percentage=0.0,
                needs_manual_review=True,
            )
        except Exception as e:
            logger.error(
                "overall_score_update_failed_on_stop",
                error=str(e),
                error_type=type(e).__name__,
                session_id=str(session_uuid),
            )
        repository.create_log(
            session_id=session_uuid,
            level="warn",
            event_type="error",
            message="Audit process stopped due to low page coverage",
            details={
                "page_coverage_score": page_coverage_score,
                "threshold": 4,
                "reason": "Insufficient data for reliable audit evaluation",
            },
        )

        try:
            score_data_for_notification = {
                "overall_percentage": 0.0,
                "flag1_percentage": (page_coverage_score / 4.0) * 100.0,
                "flag2_percentage": None,
                "flag3_percentage": 0.0,
                "needs_manual_review": True,
            }
            send_manual_review_notification(
                session_uuid,
                score_data_for_notification,
                url,
                reason=f"Page coverage {page_coverage_score}/4 below threshold. Audit stopped.",
            )
        except Exception as e:
            logger.error(
                "manual_review_notification_failed_on_page_coverage_stop",
                error=str(e),
                error_type=type(e).__name__,
                session_id=str(session_uuid),
            )

        return

    _run_audit_evaluation_for_page_types(session_uuid, domain, repository, page_types=None)

    try:
        ai_audit_data = compute_ai_audit_score(session_uuid, domain, repository)
        if ai_audit_data:
            repository.update_session_ai_audit_flag(
                session_id=session_uuid,
                ai_audit_score=ai_audit_data["score"],
                ai_audit_flag=ai_audit_data["flag"],
            )
            logger.info(
                "ai_audit_flag_stored",
                session_id=str(session_uuid),
                score=ai_audit_data["score"],
                flag=ai_audit_data["flag"],
            )
        else:
            logger.info(
                "ai_audit_flag_skipped",
                reason="no_audit_results",
                session_id=str(session_uuid),
            )
    except Exception as e:
        logger.error(
            "ai_audit_score_computation_failed",
            error=str(e),
            error_type=type(e).__name__,
            session_id=str(session_uuid),
        )

    try:
        score_data = compute_overall_audit_score(session_uuid, repository)

        repository.update_session_overall_score(
            session_id=session_uuid,
            overall_score_percentage=score_data["overall_percentage"],
            needs_manual_review=score_data["needs_manual_review"],
        )

        if score_data["needs_manual_review"]:
            send_manual_review_notification(
                session_uuid, score_data, url, reason="Overall score < 70%"
            )
            logger.info(
                "manual_review_triggered",
                session_id=str(session_uuid),
                overall_percentage=score_data["overall_percentage"],
            )
        else:
            logger.info(
                "audit_ready_for_report",
                session_id=str(session_uuid),
                overall_percentage=score_data["overall_percentage"],
            )

    except Exception as e:
        logger.error(
            "overall_score_computation_failed",
            error=str(e),
            error_type=type(e).__name__,
            session_id=str(session_uuid),
        )

    try:
        pdf_uri = generate_and_save_pdf_report(session_uuid, domain, repository)
        if pdf_uri:
            logger.info(
                "pdf_report_generated_successfully",
                session_id=str(session_uuid),
                storage_uri=pdf_uri,
            )
        else:
            logger.warning(
                "pdf_report_generation_skipped",
                session_id=str(session_uuid),
                reason="generation_failed",
            )
    except Exception as e:
        logger.error(
            "pdf_report_generation_error",
            session_id=str(session_uuid),
            error=str(e),
            error_type=type(e).__name__,
        )
