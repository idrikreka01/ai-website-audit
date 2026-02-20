#!/usr/bin/env python3
"""Normalize report data inputs to the Jinja template contract."""

from __future__ import annotations

import copy
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
DEFAULT_BASE_DATA = TEMPLATES_DIR / "sample_data.json"

PHASE_KEYS = ("awareness", "consideration", "conversion")

STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "with",
    "this",
    "from",
    "your",
    "are",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "into",
    "without",
    "have",
    "has",
    "not",
    "but",
    "can",
    "all",
    "before",
    "after",
    "both",
    "does",
    "near",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def is_reportf_payload(data: dict[str, Any]) -> bool:
    return all(k in data for k in ("url", "questions", "stage_summaries"))


def _site_from_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.netloc:
        return parsed.netloc
    return raw_url.replace("https://", "").replace("http://", "").split("/", 1)[0]


def _to_bool_result(result: str) -> bool | None:
    val = (result or "").strip().lower()
    if val == "pass":
        return True
    if val == "fail":
        return False
    return None


def _impact_from_severity(severity: int) -> str:
    if severity >= 5:
        return "High"
    if severity >= 3:
        return "Medium"
    return "Low"


def _fix_type_from_severity(severity: int) -> str:
    return "Overhaul" if severity >= 4 else "Quick Win"


def _phase_from_question(q: dict[str, Any]) -> str | None:
    cat = str(q.get("category", "")).strip().lower()
    if cat in PHASE_KEYS:
        return cat
    return None


def _tokenize(text: str) -> set[str]:
    clean = re.sub(r"[^a-z0-9]+", " ", str(text).lower())
    return {t for t in clean.split() if len(t) > 2 and t not in STOPWORDS}


def _similarity(a: str, b: str) -> float:
    a_low = str(a).lower().strip()
    b_low = str(b).lower().strip()
    if not a_low or not b_low:
        return 0.0
    if a_low in b_low or b_low in a_low:
        return 1.0

    a_tokens = _tokenize(a_low)
    b_tokens = _tokenize(b_low)
    if not a_tokens or not b_tokens:
        return 0.0

    intersection = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    coverage = intersection / len(a_tokens)
    jaccard = intersection / union if union else 0.0
    return (0.7 * coverage) + (0.3 * jaccard)


def _truncate_words(text: str, max_words: int) -> str:
    words = str(text or "").split()
    if len(words) <= max_words:
        return str(text or "").strip()
    return " ".join(words[:max_words]).rstrip(".,;:") + "..."


def _category_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text).lower())


def _map_questions_onto_base_tables(
    base_tables: list[dict[str, Any]], phase_questions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    tables = copy.deepcopy(base_tables)

    row_refs: list[tuple[int, int, str]] = []
    for table_idx, table in enumerate(tables):
        for row_idx, row in enumerate(table.get("rows", [])):
            row_refs.append((table_idx, row_idx, str(row.get("text", ""))))

    used_rows: set[tuple[int, int]] = set()
    sorted_questions = sorted(
        phase_questions,
        key=lambda q: (
            0 if _to_bool_result(str(q.get("result", ""))) is False else 1,
            -int(q.get("severity", 0) or 0),
        ),
    )

    for q in sorted_questions:
        q_text = str(q.get("question", ""))
        q_fix = str(q.get("exact_fix", ""))
        q_reason = str(q.get("reason", ""))
        raw_result = str(q.get("result", "")).strip().lower()

        best_ref: tuple[int, int] | None = None
        best_score = 0.0
        for table_idx, row_idx, row_text in row_refs:
            if (table_idx, row_idx) in used_rows:
                continue
            score = max(
                _similarity(row_text, q_text),
                0.65 * _similarity(row_text, q_fix),
                0.35 * _similarity(row_text, q_reason),
            )
            if score > best_score:
                best_score = score
                best_ref = (table_idx, row_idx)

        if best_ref is None or best_score < 0.12:
            continue

        t_idx, r_idx = best_ref
        mapped_row = tables[t_idx]["rows"][r_idx]
        mapped_row["pass"] = _to_bool_result(raw_result)
        mapped_row["is_unknown"] = raw_result == "unknown"
        mapped_row["fix_type"] = _fix_type_from_severity(int(q.get("severity", 0) or 0))
        used_rows.add(best_ref)

    return tables


def _build_phase_rating(
    phase: str,
    phase_questions: list[dict[str, Any]],
    phase_summary: str,
    category_scores_by_stage: dict[str, Any],
    stage_scores: dict[str, Any],
) -> dict[str, Any]:
    valid = [q for q in phase_questions if _to_bool_result(str(q.get("result", ""))) is not None]
    passed = sum(1 for q in valid if _to_bool_result(str(q.get("result", ""))) is True)
    total = len(valid)
    failed = total - passed

    categories = []
    for entry in category_scores_by_stage.get(phase, []) or []:
        if not isinstance(entry, dict):
            continue
        categories.append(
            {
                "name": str(entry.get("category", "Other")).strip(),
                "score": float(entry.get("score", 0) or 0),
            }
        )

    if phase in stage_scores:
        overall = round(float(stage_scores[phase]))
    else:
        overall = round((passed / total) * 100) if total else 0

    return {
        "categories": categories,
        "overall_score": overall,
        "max_score": 100,
        "recommended_changes": failed,
        "touchpoints_passed": passed,
        "points_earned": passed,
        "points_possible": total,
        "summary": str(phase_summary or "").strip()
        or (
            f"Analyzed {total} touchpoints. "
            f"{passed} passed and {failed} failed. "
            "Focus on failed rows first."
        ),
    }


def _build_phase_changelog(
    phase: str,
    phase_questions: list[dict[str, Any]],
    category_scores_by_stage: dict[str, Any],
    actionable_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    phase_categories = {
        _category_key(str(c.get("category", "")))
        for c in category_scores_by_stage.get(phase, []) or []
        if isinstance(c, dict)
    }

    matched_findings = [
        f
        for f in actionable_findings
        if isinstance(f, dict) and _category_key(str(f.get("category", ""))) in phase_categories
    ]

    if matched_findings:
        sorted_findings = sorted(
            matched_findings,
            key=lambda f: (
                0
                if str(f.get("impact", "")).strip().lower() == "high"
                else 1
                if str(f.get("impact", "")).strip().lower() == "medium"
                else 2,
                -int(f.get("severity", 0) or 0),
            ),
        )
        return [
            {
                "item": str(f.get("actionable_finding", "")).strip(),
                "impact": str(f.get("impact", "")).strip() or "Medium",
            }
            for f in sorted_findings
            if str(f.get("actionable_finding", "")).strip()
        ]

    failed = [q for q in phase_questions if _to_bool_result(str(q.get("result", ""))) is False]
    failed_sorted = sorted(failed, key=lambda q: -int(q.get("severity", 0) or 0))
    return [
        {
            "item": str(q.get("exact_fix") or q.get("question") or "").strip(),
            "impact": _impact_from_severity(int(q.get("severity", 0) or 0)),
        }
        for q in failed_sorted
    ]


def adapt_reportf_to_template(reportf_data: dict[str, Any], base_data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = copy.deepcopy(base_data if base_data is not None else load_json(DEFAULT_BASE_DATA))

    questions = [q for q in reportf_data.get("questions", []) if isinstance(q, dict)]
    phase_questions: dict[str, list[dict[str, Any]]] = {k: [] for k in PHASE_KEYS}
    for q in questions:
        phase = _phase_from_question(q)
        if phase:
            phase_questions[phase].append(q)

    stage_summary_map = {
        str(s.get("stage", "")).strip().lower(): str(s.get("summary", "")).strip()
        for s in reportf_data.get("stage_summaries", [])
        if isinstance(s, dict)
    }
    category_scores_by_stage = reportf_data.get("category_scores_by_stage", {}) or {}
    stage_scores = reportf_data.get("stage_scores", {}) or {}
    actionable_findings = [f for f in reportf_data.get("actionable_findings", []) if isinstance(f, dict)]
    stage_descriptions = (
        reportf_data.get("storefront_report_card", {}).get("stage_descriptions", {}) or {}
    )

    raw_url = str(reportf_data.get("url", "")).strip()
    site = _site_from_url(raw_url)
    data["meta"]["site_url"] = site
    data["meta"]["brand_name"] = site
    data["meta"]["report_date"] = datetime.now().strftime("%B %d, %Y")

    # Keep section-2 issues static from sample_data.json.

    phase_change_logs: dict[str, list[dict[str, Any]]] = {}

    for phase in PHASE_KEYS:
        qs = phase_questions[phase]
        data[phase]["audit_tables"] = _map_questions_onto_base_tables(data[phase]["audit_tables"], qs)
        data[phase]["rating"] = _build_phase_rating(
            phase,
            qs,
            stage_summary_map.get(phase, ""),
            category_scores_by_stage,
            stage_scores,
        )

        phase_change_logs[phase] = _build_phase_changelog(
            phase,
            qs,
            category_scores_by_stage,
            actionable_findings,
        )

    data["phase_change_logs"] = phase_change_logs

    # Performance summary cards.
    for phase in PHASE_KEYS:
        score = data[phase]["rating"]["overall_score"]
        phase_note = str(stage_descriptions.get(phase, "")).strip()
        data["performance_summary"][phase]["score"] = score
        data["performance_summary"][phase]["note"] = phase_note or (
            "Strong performance" if score >= 80 else "Needs focused improvements"
        )

    final_thoughts = str(
        reportf_data.get("storefront_report_card", {}).get("final_thoughts", "")
    ).strip()
    if final_thoughts:
        data["performance_summary"]["final_thoughts"] = final_thoughts
    elif reportf_data.get("overall_score") is not None:
        overall = round(float(reportf_data.get("overall_score", 0) or 0), 2)
        data["performance_summary"]["final_thoughts"] = (
            f"Overall audit score is {overall}/100. "
            "Prioritize high-impact failures in each phase changelog for fastest gains."
        )

    # Keep this empty because phase-level changelogs are now rendered after each phase.
    data["change_log_table"] = []

    return data


def ensure_template_data(raw_data: dict[str, Any], base_data: dict[str, Any] | None = None) -> dict[str, Any]:
    if is_reportf_payload(raw_data):
        return adapt_reportf_to_template(raw_data, base_data=base_data)
    return raw_data
