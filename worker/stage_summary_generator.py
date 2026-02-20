"""
Stage summary generator: AI-generated summaries per stage (Awareness/Consideration/Conversion).

Follows developer spec for Revenue Recovery Audit stage summaries:
- One paragraph, ~5 sentences
- Buyer perspective, helpful consultant tone
- Category severity sum logic for theme selection
- Tier rules (Tier 1 eligible, Tier 2 conditional, Tier 3 never)
- Evidence rules (quote only html safe, screenshot describe location)
- 5-sentence template structure
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from openai import OpenAI

from shared.config import get_config
from shared.logging import get_logger
from worker.repository import AuditRepository

logger = get_logger(__name__)

STAGES = ["Awareness", "Consideration", "Conversion"]

STAGE_FOCUS_ORDER = {
    "Awareness": ["clarity", "trust", "navigation", "performance"],
    "Consideration": ["product info", "proof", "objections", "trust"],
    "Conversion": ["friction", "payment trust", "error handling", "performance"],
}

CATEGORY_MAPPING = {
    "clarity": ["clarity", "messaging", "headline", "value prop"],
    "trust": ["trust", "security", "credibility", "reputation"],
    "navigation": ["navigation", "menu", "links", "structure"],
    "performance": ["performance", "speed", "loading", "optimization"],
    "product info": ["product", "description", "details", "specifications"],
    "proof": ["proof", "reviews", "testimonials", "social proof"],
    "objections": ["objections", "concerns", "barriers", "hesitation"],
    "friction": ["friction", "steps", "complexity", "barriers"],
    "payment trust": ["payment", "checkout", "security", "trust"],
    "error handling": ["error", "validation", "messages", "handling"],
}


def _map_to_category(bar_chart_category: str) -> str:
    bar_lower = (bar_chart_category or "").lower()
    for category, keywords in CATEGORY_MAPPING.items():
        if any(kw in bar_lower for kw in keywords):
            return category
    return "other"


def _compute_category_severity_sums(
    questions: list[dict], tier_filter: Optional[list[int]] = None
) -> dict[str, int]:
    category_sums = defaultdict(int)
    for q in questions:
        result = (q.get("result") or "").lower()
        if result != "fail":
            continue
        tier = q.get("tier", 1)
        if tier_filter and tier not in tier_filter:
            continue
        severity = q.get("severity", 1)
        category = _map_to_category(q.get("bar_chart_category", ""))
        category_sums[category] += severity
    return dict(category_sums)


def _select_main_theme(stage: str, category_sums: dict[str, int]) -> str:
    if not category_sums:
        return "general"
    max_sum = max(category_sums.values())
    candidates = [cat for cat, s in category_sums.items() if s == max_sum]
    if len(candidates) == 1:
        return candidates[0]
    focus_order = STAGE_FOCUS_ORDER.get(stage, [])
    for cat in focus_order:
        if cat in candidates:
            return cat
    return candidates[0]


def _get_eligible_questions(
    questions: list[dict],
    main_theme: str,
    tier1_failed_count: int,
    tier2_category_sum: int,
) -> list[dict]:
    eligible = []
    for q in questions:
        result = (q.get("result") or "").lower()
        if result != "fail":
            continue
        tier = q.get("tier", 1)
        category = _map_to_category(q.get("bar_chart_category", ""))
        if tier == 1:
            eligible.append(q)
        elif tier == 2:
            if (
                tier2_category_sum >= 7
                or category == main_theme
                or (tier1_failed_count == 0 and tier2_category_sum > 0)
            ):
                eligible.append(q)
    return eligible


def _build_evidence_context(session_id: UUID, stage: str, repository: AuditRepository) -> str:
    page_types = {
        "Awareness": ["homepage"],
        "Consideration": ["product"],
        "Conversion": ["cart", "checkout"],
    }
    relevant_pages = page_types.get(stage, [])
    evidence_parts = []
    for page_type in relevant_pages:
        pages = repository.get_pages_by_session_id(session_id)
        page_found = any(p.get("page_type") == page_type and p.get("status") == "ok" for p in pages)
        if page_found:
            evidence_parts.append(f"- {page_type} page loaded successfully")
        else:
            evidence_parts.append(f"- {page_type} page missing or failed")
    return "\n".join(evidence_parts) if evidence_parts else "- No page context available"


def _calculate_confidence_score(session_id: UUID, stage: str, repository: AuditRepository) -> int:
    score = 10
    page_types = {
        "Awareness": ["homepage"],
        "Consideration": ["product"],
        "Conversion": ["cart", "checkout"],
    }
    pages = repository.get_pages_by_session_id(session_id)
    for page_type in page_types.get(stage, []):
        page_ok = any(p.get("page_type") == page_type and p.get("status") == "ok" for p in pages)
        if not page_ok:
            score -= 2
    if stage == "Conversion":
        session_data = repository.get_session_by_id(session_id)
        functional_flow_score = session_data.get("functional_flow_score", 0)
        if functional_flow_score < 3:
            score -= 3
    return max(1, min(10, score))


def _build_summary_prompt(
    stage: str,
    main_theme: str,
    eligible_questions: list[dict],
    passed_count: int,
    total_count: int,
    score: float,
    url: str,
    evidence_context: str,
) -> str:
    failed_count = len(eligible_questions)
    theme_questions = [
        q
        for q in eligible_questions
        if _map_to_category(q.get("bar_chart_category", "")) == main_theme
    ]
    theme_questions.sort(key=lambda q: q.get("severity", 1), reverse=True)
    if len(theme_questions) > 10:
        theme_questions = theme_questions[:10]
    failed_items = []
    for q in theme_questions:
        question_text = q.get("question", "").strip()
        exact_fix = q.get("exact_fix", "").strip()
        bar_category = q.get("bar_chart_category", "")
        if question_text:
            item = f"- {question_text}"
            if exact_fix:
                item += f" | Fix: {exact_fix}"
            if bar_category:
                item += f" | Category: {bar_category}"
            failed_items.append(item)
    failed_section = "\n".join(failed_items) if failed_items else "None"
    if len(eligible_questions) > len(theme_questions):
        failed_section += f"\n... and {len(eligible_questions) - len(theme_questions)} more issues"

    prompt = f"""You are writing a stage summary for a Revenue Recovery Audit.

STAGE: {stage}
WEBSITE: {url}
STAGE SCORE: {score:.1f}%
PASSED CHECKS: {passed_count} out of {total_count}
FAILED CHECKS: {failed_count}

MAIN THEME: {main_theme}

FAILED ISSUES (main theme focus):
{failed_section}

EVIDENCE CONTEXT:
{evidence_context}

OUTPUT REQUIREMENTS:
- Write ONE paragraph only (no bullets, no numbered lists)
- Roughly 5 sentences, each medium length (not extremely short, avoid long run-ons)
- Tone: Helpful consultant, firm and friendly, no hype
- Voice: Neutral, buyer perspective (describe what buyer may notice, miss, or hesitate on)
- Use "we" sparingly
- Impact language allowed but non-insulting (e.g. "likely lowering conversions")
- Banned: leverage, optimize, dynamic, game changer, fluff adjectives
- Numbers: Use "a few", "several", "most" - NEVER exact counts like "13 issues"
- Do NOT mention changelog or checklist existence

EVIDENCE RULES:
- Quote exact text ONLY if it comes from html safe evidence payload (structured DOM selectors)
- Screenshot-based issues: Describe location/behavior in plain language, NO quotes
- Unverified claims: Use "may" or "likely" to hedge
- Maximum ONE short quote per paragraph
- Otherwise use plain language pointers like "on your product description section"

5-SENTENCE TEMPLATE:
1. Positive stage read: What is working from buyer perspective
2. Main theme and impact: Biggest conversion blocker for this stage and why it matters
3. Evidence pointer: Where issue shows up (one quote if html safe, otherwise location description)
4. Simple fix: Non-technical action owner can take (direct action language)
5. Outcome or test: Expected buyer behavior improvement OR A/B test idea tied to main theme

CLEAN STAGE RULES:
- If stage is near perfect: Use "Praise plus one micro improvement framed as a test, not a fix"
- Test target: messaging (Awareness), product proof (Consideration), friction (Conversion)

STAGE BOUNDARIES:
- Awareness: Only homepage and navigation issues
- Consideration: Only product page issues  
- Conversion: Only checkout and purchase path issues

Generate the summary now:"""

    return prompt


def generate_stage_summary(
    stage: str,
    questions: list[dict],
    url: str,
    session_id: UUID,
    repository: AuditRepository,
    model: str = "gpt-5.2",
) -> dict:
    """
    Generate AI summary for a specific stage following developer spec.

    Args:
        stage: Stage name (Awareness/Consideration/Conversion)
        questions: List of question result dicts for this stage
        url: Website URL being audited
        session_id: Session UUID for evidence context
        repository: AuditRepository for page context
        model: OpenAI model to use

    Returns:
        Dict with summary text, metadata, confidence score, and cost info
    """
    total_count = len(questions)
    if total_count == 0:
        logger.warning("stage_summary_no_questions", stage=stage)
        return {
            "stage": stage,
            "summary": f"No questions found for {stage} stage.",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": model,
            "token_usage": {"input_tokens": 0, "output_tokens": 0},
            "cost_usd": 0.0,
            "confidence_score": 1,
            "manual_review_flag": True,
            "manual_review_reasons": ["No questions found"],
            "selected_main_theme": "none",
        }

    passed_count = sum(1 for q in questions if (q.get("result") or "").lower() == "pass")
    score = calculate_stage_score(questions)

    tier1_questions = [q for q in questions if q.get("tier", 1) == 1]
    tier2_questions = [q for q in questions if q.get("tier", 1) == 2]
    tier1_failed = [q for q in tier1_questions if (q.get("result") or "").lower() == "fail"]
    tier2_failed = [q for q in tier2_questions if (q.get("result") or "").lower() == "fail"]

    tier2_category_sums = _compute_category_severity_sums(tier2_questions, tier_filter=[2])
    all_category_sums = _compute_category_severity_sums(questions, tier_filter=[1, 2])

    if len(tier1_failed) == 0 and len(tier2_failed) == 0:
        main_theme = "general"
        eligible_questions = []
    elif len(tier1_failed) == 0 and len(tier2_failed) > 0:
        main_theme = _select_main_theme(stage, tier2_category_sums)
        tier2_sum = tier2_category_sums.get(main_theme, 0)
        eligible_questions = _get_eligible_questions(questions, main_theme, 0, tier2_sum)
    else:
        main_theme = _select_main_theme(stage, all_category_sums)
        tier2_sum = tier2_category_sums.get(main_theme, 0)
        eligible_questions = _get_eligible_questions(
            questions, main_theme, len(tier1_failed), tier2_sum
        )

    eligible_questions.sort(key=lambda q: q.get("severity", 1), reverse=True)

    if len(eligible_questions) >= 10:
        eligible_questions = [
            q
            for q in eligible_questions
            if _map_to_category(q.get("bar_chart_category", "")) == main_theme
        ]

    evidence_context = _build_evidence_context(session_id, stage, repository)
    confidence_score = _calculate_confidence_score(session_id, stage, repository)

    pages = repository.get_pages_by_session_id(session_id)
    page_types = {
        "Awareness": ["homepage"],
        "Consideration": ["product"],
        "Conversion": ["cart", "checkout"],
    }

    manual_review_reasons = []
    hard_flag_triggered = False

    for page_type in page_types.get(stage, []):
        page_ok = any(p.get("page_type") == page_type and p.get("status") == "ok" for p in pages)
        if not page_ok:
            reason = f"{page_type} page failed to load"
            manual_review_reasons.append(reason)
            hard_flag_triggered = True

    if stage == "Conversion":
        session_data = repository.get_session_by_id(session_id)
        functional_flow_score = session_data.get("functional_flow_score", 0)
        if functional_flow_score < 3:
            manual_review_reasons.append("Checkout inaccessible")
            hard_flag_triggered = True

    manual_review_flag = confidence_score < 7 or hard_flag_triggered

    if confidence_score < 7 and not hard_flag_triggered:
        manual_review_reasons.append(f"Confidence score {confidence_score} is below threshold (7)")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        try:
            config = get_config()
            api_key = config.openai_api_key
        except Exception:
            pass

    if not api_key:
        logger.error("openai_api_key_missing_for_stage_summary", stage=stage)
        return {
            "stage": stage,
            "summary": f"Summary unavailable for {stage} (OpenAI API key not configured).",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": model,
            "token_usage": {"input_tokens": 0, "output_tokens": 0},
            "cost_usd": 0.0,
            "confidence_score": confidence_score,
            "manual_review_flag": manual_review_flag,
            "manual_review_reasons": manual_review_reasons,
            "selected_main_theme": main_theme,
        }

    client = OpenAI(api_key=api_key)
    prompt = _build_summary_prompt(
        stage,
        main_theme,
        eligible_questions,
        passed_count,
        total_count,
        score,
        url,
        evidence_context,
    )

    input_per_1m = float(os.getenv("OPENAI_PRICE_INPUT_PER_1M", "2.50"))
    output_per_1m = float(os.getenv("OPENAI_PRICE_OUTPUT_PER_1M", "10.00"))

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Expert e-commerce consultant. Strategic insights, "
                        "optimization, revenue. Concise, buyer-focused."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_completion_tokens=400,
        )

        summary_text = response.choices[0].message.content.strip()

        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        cost_usd = (input_tokens / 1_000_000 * input_per_1m) + (
            output_tokens / 1_000_000 * output_per_1m
        )

        logger.info(
            "stage_summary_generated",
            stage=stage,
            model=model,
            main_theme=main_theme,
            confidence_score=confidence_score,
            manual_review_flag=manual_review_flag,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )

        return {
            "stage": stage,
            "summary": summary_text,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": model,
            "token_usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            "cost_usd": cost_usd,
            "confidence_score": confidence_score,
            "manual_review_flag": manual_review_flag,
            "manual_review_reasons": manual_review_reasons,
            "selected_main_theme": main_theme,
        }

    except Exception as e:
        logger.error(
            "stage_summary_generation_failed",
            stage=stage,
            error=str(e),
            error_type=type(e).__name__,
        )
        return {
            "stage": stage,
            "summary": f"Summary generation failed for {stage} stage: {str(e)}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": model,
            "token_usage": {"input_tokens": 0, "output_tokens": 0},
            "cost_usd": 0.0,
            "confidence_score": confidence_score,
            "manual_review_flag": True,
            "manual_review_reasons": [f"Generation error: {str(e)}"],
            "selected_main_theme": main_theme,
        }


def calculate_stage_score(questions: list[dict]) -> float:
    """
    Calculate score percentage for a stage based on passed/failed questions.

    Args:
        questions: List of question result dicts with 'result' field

    Returns:
        Score as percentage (0-100)
    """
    if not questions:
        return 0.0

    passed = sum(1 for q in questions if (q.get("result") or "").lower() == "pass")
    total = len(questions)

    return (passed / total) * 100.0 if total > 0 else 0.0


def generate_stage_summaries(
    session_id: UUID,
    repository: AuditRepository,
    model: str = "gpt-5.2",
) -> list[dict]:
    """
    Generate AI summaries for all stages (Awareness/Consideration/Conversion).

    Args:
        session_id: Session UUID
        repository: AuditRepository instance
        model: OpenAI model to use

    Returns:
        List of summary dicts, one per stage
    """
    session_data = repository.get_session_by_id(session_id)
    if not session_data:
        logger.warning(
            "session_not_found_for_stage_summaries",
            session_id=str(session_id),
        )
        return []

    from urllib.parse import urlparse

    domain = urlparse(session_data.get("url", "")).netloc.replace("www.", "")
    session_id_str = f"{domain}__{session_id}"

    results = repository.get_audit_results_by_session_id(session_id_str)
    if not results:
        logger.warning(
            "no_results_for_stage_summaries",
            session_id=str(session_id),
        )
        return []

    questions_map = {}
    all_questions = repository.list_questions()
    for question in all_questions:
        questions_map[question["question_id"]] = question

    tier1_results = []
    tier2_results = []
    tier3_results = []

    for result in results:
        question_id = result["question_id"]
        question = questions_map.get(question_id)
        if not question:
            continue

        tier = question.get("tier", 1)
        result_data = {
            "question_id": question_id,
            "question": question.get("question", ""),
            "category": question.get("category", ""),
            "bar_chart_category": question.get("bar_chart_category", ""),
            "exact_fix": question.get("exact_fix", ""),
            "result": (result.get("result") or "").lower(),
            "reason": result.get("reason", ""),
            "tier": tier,
            "severity": question.get("severity", 1),
            "page_type": question.get("page_type", ""),
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
    elif not tier2_passed:
        report_questions = tier1_results + tier2_results
    else:
        report_questions = tier1_results + tier2_results + tier3_results

    questions_by_stage = {stage: [] for stage in STAGES}

    for result_data in report_questions:
        category = result_data.get("category", "")
        if category in STAGES:
            questions_by_stage[category].append(result_data)

    url = session_data.get("url", "")
    summaries = []

    for stage in STAGES:
        stage_questions = questions_by_stage[stage]
        summary = generate_stage_summary(stage, stage_questions, url, session_id, repository, model)

        try:
            repository.save_stage_summary(
                session_id=session_id,
                stage=summary["stage"],
                summary=summary["summary"],
                model_version=summary["model_version"],
                token_usage=summary["token_usage"],
                cost_usd=summary["cost_usd"],
            )
            logger.debug(
                "stage_summary_saved_to_db",
                session_id=str(session_id),
                stage=stage,
            )
        except Exception as e:
            logger.warning(
                "stage_summary_save_failed",
                session_id=str(session_id),
                stage=stage,
                error=str(e),
                error_type=type(e).__name__,
            )

        summaries.append(summary)

    total_cost = sum(s.get("cost_usd", 0.0) for s in summaries)
    logger.info(
        "stage_summaries_generated",
        session_id=str(session_id),
        stage_count=len(summaries),
        total_cost_usd=total_cost,
    )

    return [
        {
            "stage": s["stage"],
            "summary": s["summary"],
            "generated_at": s["generated_at"],
            "model_version": s["model_version"],
        }
        for s in summaries
    ]
