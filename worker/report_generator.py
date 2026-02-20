"""
Report generator: Creates audit reports based on tier logic and severity ordering.

Tier Logic:
- Tier 1 questions must pass before Tier 2 questions are included
- If any Tier 1 question fails, only Tier 1 questions appear in report

Severity Ordering:
- Questions ordered by severity (highest to lowest)
- Uses exact_fix from questions table for report content
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID

from shared.logging import get_logger
from worker.repository import AuditRepository

logger = get_logger(__name__)


def _normalize_result(value: Optional[str]) -> str:
    v = (value or "fail").lower()
    return v if v in ("pass", "fail", "unknown") else "fail"


def _calculate_weighted_category_scores(questions: list[dict]) -> list[dict]:
    """
    Calculate weighted scores per bar_chart_category.

    Weighting formula:
    - Tier weight: Tier 1 = 3, Tier 2 = 2, Tier 3 = 1
    - Severity weight: 5 = 5, 4 = 4, 3 = 3, 2 = 2, 1 = 1
    - Combined weight = tier_weight * severity_weight
    - Question score = weight * (1 if pass, 0 if fail)
    - Category score = sum(weighted_scores) / sum(weights) * 100

    Returns list of dicts with category, score, and metadata.
    """
    category_data = defaultdict(
        lambda: {"weighted_score": 0.0, "total_weight": 0.0, "questions": []}
    )

    tier_weights = {1: 3, 2: 2, 3: 1}

    for question in questions:
        category = question.get("bar_chart_category", "Unknown")
        tier = question.get("tier", 1)
        severity = question.get("severity", 1)
        result = (question.get("result") or "fail").lower()
        if result not in ("pass", "fail", "unknown"):
            result = "fail"

        tier_weight = tier_weights.get(tier, 1)
        severity_weight = severity
        combined_weight = tier_weight * severity_weight

        if result == "unknown":
            category_data[category]["questions"].append(
                {
                    "question_id": question.get("question_id"),
                    "tier": tier,
                    "severity": severity,
                    "weight": combined_weight,
                    "result": result,
                }
            )
            continue
        question_score = 1.0 if result == "pass" else 0.0
        weighted_score = combined_weight * question_score
        category_data[category]["weighted_score"] += weighted_score
        category_data[category]["total_weight"] += combined_weight
        category_data[category]["questions"].append(
            {
                "question_id": question.get("question_id"),
                "tier": tier,
                "severity": severity,
                "weight": combined_weight,
                "result": result,
            }
        )

    category_scores = []
    for category, data in sorted(category_data.items()):
        if data["total_weight"] > 0:
            score = (data["weighted_score"] / data["total_weight"]) * 100
        else:
            score = 0.0

        category_scores.append(
            {
                "category": category,
                "score": round(score, 2),
                "total_questions": len(data["questions"]),
                "total_weight": round(data["total_weight"], 2),
            }
        )

    return sorted(category_scores, key=lambda x: x["score"], reverse=True)


def _calculate_overall_score_from_categories(category_scores: list[dict]) -> float:
    """
    Calculate overall score from category scores using weighted average.

    Formula: sum(category_score × category_weight) / sum(category_weights) × 100

    Returns overall score (0-100, rounded to 2 decimals).
    """
    if not category_scores:
        return 0.0

    total_weighted_score = 0.0
    total_weight = 0.0

    for cat in category_scores:
        score = cat.get("score", 0.0)
        weight = cat.get("total_weight", 0.0)

        total_weighted_score += (score / 100.0) * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0

    overall_score = (total_weighted_score / total_weight) * 100.0
    return round(overall_score, 2)


def _group_category_scores_by_stage(category_scores: list[dict], questions: list[dict]) -> dict:
    """
    Group category scores by stage (Awareness, Consideration, Conversion).

    Returns dict with structure:
    {
        "awareness": [category_scores...],
        "consideration": [category_scores...],
        "conversion": [category_scores...]
    }
    """
    stages = ["Awareness", "Consideration", "Conversion"]
    stage_categories = {stage.lower(): [] for stage in stages}

    category_to_stage = {}
    for question in questions:
        category = question.get("bar_chart_category", "")
        stage = question.get("category", "")
        if stage in stages:
            category_to_stage[category] = stage.lower()

    for cat_score in category_scores:
        category = cat_score.get("category", "")
        stage = category_to_stage.get(category)
        if stage and stage in stage_categories:
            stage_categories[stage].append(cat_score)

    return stage_categories


def _calculate_stage_scores(category_scores: list[dict], questions: list[dict]) -> dict:
    """
    Calculate scores per stage (Awareness, Consideration, Conversion).

    Groups categories by stage based on question categories and calculates
    weighted average per stage.

    Returns dict with stage scores: {awareness: float, consideration: float, conversion: float}
    """
    category_scores_by_stage = _group_category_scores_by_stage(category_scores, questions)

    stage_scores = {}
    for stage, categories in category_scores_by_stage.items():
        stage_score = _calculate_overall_score_from_categories(categories)
        stage_scores[stage] = stage_score

    return stage_scores


def _generate_actionable_findings(
    questions: list[dict], session_id: UUID, repository
) -> list[dict]:
    """
    Generate actionable findings changelog from failed questions.

    Impact levels:
    - High: Tier 1 with Severity 4-5, or Tier 2 with Severity 5
    - Medium: Tier 1 with Severity 2-3, Tier 2 with Severity 3-4, or Tier 3 with Severity 5
    - Low: All other combinations

    Returns list of dicts with actionable_finding and impact, sorted by impact priority.
    Replaces [X] placeholders with actual load times from pages.
    """
    failed_questions = [q for q in questions if (q.get("result") or "").lower() == "fail"]

    pages = repository.get_pages_by_session_id(session_id)
    page_load_times = {}
    for page in pages:
        page_type = page.get("page_type", "")
        load_timings = page.get("load_timings", {})
        if isinstance(load_timings, dict):
            total_ms = load_timings.get("total_load_duration_ms")
            if total_ms is not None:
                load_seconds = round(total_ms / 1000.0, 1)
                if page_type not in page_load_times:
                    page_load_times[page_type] = []
                page_load_times[page_type].append(load_seconds)

    for page_type in page_load_times:
        if page_load_times[page_type]:
            page_load_times[page_type] = max(page_load_times[page_type])

    impact_levels = {
        "High": [],
        "Medium": [],
        "Low": [],
    }

    for question in failed_questions:
        tier = question.get("tier", 1)
        severity = question.get("severity", 1)
        exact_fix = question.get("exact_fix", "")
        category = question.get("bar_chart_category", "")
        page_type = question.get("page_type", "")

        if not exact_fix:
            continue

        if "[X]" in exact_fix:
            load_time = page_load_times.get(page_type)
            if load_time is not None:
                exact_fix = exact_fix.replace("[X]", str(load_time))
            else:
                exact_fix = exact_fix.replace("[X]", "unknown")

        impact = "Low"
        if (tier == 1 and severity >= 4) or (tier == 2 and severity == 5):
            impact = "High"
        elif (
            (tier == 1 and severity >= 2)
            or (tier == 2 and severity >= 3)
            or (tier == 3 and severity == 5)
        ):
            impact = "Medium"

        finding = {
            "actionable_finding": exact_fix,
            "impact": impact,
            "category": category,
            "tier": tier,
            "severity": severity,
            "question_id": question.get("question_id"),
        }

        impact_levels[impact].append(finding)

    actionable_findings = []
    for impact in ["High", "Medium", "Low"]:
        findings = impact_levels[impact]
        findings.sort(key=lambda x: (x["tier"], x["severity"]), reverse=True)
        actionable_findings.extend(findings)

    return actionable_findings


def generate_audit_report(session_id: UUID, repository: AuditRepository) -> dict:
    """
    Generate audit report for a session.

    Returns dict with:
    - session_id
    - overall_score_percentage
    - tier1_passed: bool
    - questions: list of question results ordered by severity DESC
    """
    session_data = repository.get_session_by_id(session_id)
    if not session_data:
        logger.warning(
            "session_not_found_for_report",
            session_id=str(session_id),
        )
        return {
            "session_id": str(session_id),
            "error": "Session not found",
        }

    page_coverage_score = session_data.get("page_coverage_score", 0)
    if page_coverage_score < 4:
        logger.warning(
            "report_generation_stopped_low_page_coverage",
            session_id=str(session_id),
            page_coverage_score=page_coverage_score,
            reason="Page coverage < 4, insufficient data for reliable report",
        )
        return {
            "session_id": str(session_id),
            "url": session_data.get("url", ""),
            "overall_score_percentage": session_data.get("overall_score_percentage"),
            "needs_manual_review": True,
            "manual_review_reason": (
                f"Page coverage {page_coverage_score} below threshold (4). Insufficient data."
            ),
            "page_coverage_score": page_coverage_score,
            "questions": [],
            "stage_summaries": [],
            "category_scores": [],
            "actionable_findings": [],
            "storefront_report_card": {},
        }

    domain = urlparse(session_data.get("url", "")).netloc.replace("www.", "")
    session_id_str = f"{domain}__{session_id}"

    results = repository.get_audit_results_by_session_id(session_id_str)
    if not results:
        logger.warning(
            "no_results_found_for_report",
            session_id=str(session_id),
            session_id_str=session_id_str,
        )
        return {
            "session_id": str(session_id),
            "overall_score_percentage": session_data.get("overall_score_percentage"),
            "tier1_passed": False,
            "questions": [],
        }

    questions_map = {}
    all_questions = repository.list_questions()
    for question in all_questions:
        questions_map[question["question_id"]] = question

    pages = repository.get_pages_by_session_id(session_id)
    page_load_times = {}
    for page in pages:
        page_type = page.get("page_type", "")
        load_timings = page.get("load_timings", {})
        if isinstance(load_timings, dict):
            total_ms = load_timings.get("total_load_duration_ms")
            if total_ms is not None:
                load_seconds = round(total_ms / 1000.0, 1)
                if page_type not in page_load_times:
                    page_load_times[page_type] = []
                page_load_times[page_type].append(load_seconds)

    for page_type in page_load_times:
        if page_load_times[page_type]:
            page_load_times[page_type] = max(page_load_times[page_type])

    tier1_results = []
    tier2_results = []
    tier3_results = []

    for result in results:
        question_id = result["question_id"]
        question = questions_map.get(question_id)
        if not question:
            continue

        tier = question.get("tier", 1)
        exact_fix = question.get("exact_fix", "")
        page_type = question.get("page_type", "")

        if "[X]" in exact_fix:
            load_time = page_load_times.get(page_type)
            if load_time is not None:
                exact_fix = exact_fix.replace("[X]", str(load_time))
            else:
                exact_fix = exact_fix.replace("[X]", "unknown")

        result_data = {
            "question_id": question_id,
            "question": question.get("question", ""),
            "category": question.get("category", ""),
            "bar_chart_category": question.get("bar_chart_category", ""),
            "tier": tier,
            "severity": question.get("severity", 1),
            "exact_fix": exact_fix,
            "page_type": page_type,
            "result": _normalize_result(result.get("result")),
            "reason": result.get("reason", ""),
            "confidence_score": result.get("confidence_score"),
        }

        if tier == 1:
            tier1_results.append(result_data)
        elif tier == 2:
            tier2_results.append(result_data)
        elif tier == 3:
            tier3_results.append(result_data)

    tier1_passed = all(r["result"] == "pass" for r in tier1_results)
    tier2_passed = all(r["result"] == "pass" for r in tier2_results) if tier1_passed else False

    if not tier1_passed:
        report_questions = tier1_results
        logger.info(
            "report_tier1_failed",
            session_id=str(session_id),
            tier1_failed_count=sum(1 for r in tier1_results if r["result"] != "pass"),
        )
    elif not tier2_passed:
        report_questions = tier1_results + tier2_results
        logger.info(
            "report_tier2_failed",
            session_id=str(session_id),
            tier1_count=len(tier1_results),
            tier2_count=len(tier2_results),
            tier2_failed_count=sum(1 for r in tier2_results if r["result"] != "pass"),
        )
    else:
        report_questions = tier1_results + tier2_results + tier3_results
        logger.info(
            "report_all_tiers_passed",
            session_id=str(session_id),
            tier1_count=len(tier1_results),
            tier2_count=len(tier2_results),
            tier3_count=len(tier3_results),
        )

    report_questions.sort(key=lambda x: x["severity"], reverse=True)

    stage_summaries = []
    try:
        existing_summaries = repository.get_stage_summaries_by_session(session_id)
        if existing_summaries:
            stage_summaries = [
                {
                    "stage": s["stage"],
                    "summary": s["summary"],
                    "generated_at": (
                        s["generated_at"].isoformat()
                        if hasattr(s["generated_at"], "isoformat")
                        else str(s["generated_at"])
                    ),
                    "model_version": s["model_version"],
                }
                for s in existing_summaries
            ]
            logger.info(
                "stage_summaries_loaded_from_db",
                session_id=str(session_id),
                summary_count=len(stage_summaries),
            )
        else:
            from worker.stage_summary_generator import generate_stage_summaries

            stage_summaries = generate_stage_summaries(session_id, repository)
            logger.info(
                "stage_summaries_generated_and_included",
                session_id=str(session_id),
                summary_count=len(stage_summaries),
            )
    except Exception as e:
        logger.warning(
            "stage_summaries_generation_failed",
            session_id=str(session_id),
            error=str(e),
            error_type=type(e).__name__,
        )

    category_scores = _calculate_weighted_category_scores(report_questions)
    actionable_findings = _generate_actionable_findings(report_questions, session_id, repository)

    category_scores_by_stage = _group_category_scores_by_stage(category_scores, report_questions)
    overall_score = _calculate_overall_score_from_categories(category_scores)
    stage_scores = _calculate_stage_scores(category_scores, report_questions)

    storefront_report_card = {}
    try:
        existing_card = repository.get_storefront_report_card_by_session(session_id)
        if existing_card:
            storefront_report_card = {
                "stage_descriptions": existing_card.get("stage_descriptions", {}),
                "final_thoughts": existing_card.get("final_thoughts", ""),
            }
            logger.info(
                "storefront_report_card_loaded_from_db",
                session_id=str(session_id),
            )
        else:
            from worker.storefront_report_card import generate_storefront_report_card

            generated_card = generate_storefront_report_card(
                url=session_data.get("url", ""),
                stage_scores=stage_scores,
                stage_summaries=stage_summaries,
                actionable_findings=actionable_findings,
                overall_score=overall_score,
            )

            repository.save_storefront_report_card(
                session_id=session_id,
                stage_descriptions=generated_card.get("stage_descriptions", {}),
                final_thoughts=generated_card.get("final_thoughts", ""),
                model_version=generated_card.get("model_version", "gpt-5.2"),
                token_usage=generated_card.get("token_usage", {}),
                cost_usd=generated_card.get("cost_usd", 0.0),
            )

            storefront_report_card = {
                "stage_descriptions": generated_card.get("stage_descriptions", {}),
                "final_thoughts": generated_card.get("final_thoughts", ""),
            }
            logger.info(
                "storefront_report_card_generated_and_saved",
                session_id=str(session_id),
                cost_usd=generated_card.get("cost_usd", 0.0),
            )
    except Exception as e:
        logger.warning(
            "storefront_report_card_generation_failed",
            session_id=str(session_id),
            error=str(e),
            error_type=type(e).__name__,
        )

    return {
        "session_id": str(session_id),
        "url": session_data.get("url", ""),
        "overall_score_percentage": session_data.get("overall_score_percentage"),
        "overall_score": overall_score,
        "stage_scores": stage_scores,
        "category_scores": category_scores,
        "category_scores_by_stage": category_scores_by_stage,
        "storefront_report_card": storefront_report_card,
        "needs_manual_review": session_data.get("needs_manual_review", False),
        "tier1_passed": tier1_passed,
        "tier2_passed": tier2_passed,
        "tier3_included": tier1_passed and tier2_passed,
        "questions": report_questions,
        "stage_summaries": stage_summaries,
        "actionable_findings": actionable_findings,
    }
