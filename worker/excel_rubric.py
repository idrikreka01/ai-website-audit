"""
Excel rubric workbook generation for audit sessions.

Builds a session-level workbook with Questions and Output tabs, then returns bytes
for storage as an excel_rubric_xlsx artifact.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import json
from openpyxl import Workbook

from shared.config import get_config
from shared.logging import get_logger
from worker.repository import AuditRepository
from worker.storage import (
    build_excel_rubric_artifact_path,
    get_storage_uri,
    write_binary,
)

logger = get_logger(__name__)


QUESTIONS_HEADERS = [
    "Category",
    "Questions",
    "AI",
    "Model",
    "Tier",
    "Severity",
    "Page",
    "Bar Chart Category (In Audit)",
    "Exact Fix:",
]

OUTPUT_HEADERS = [
    "Category",
    "Questions",
    "AI grade",
]


def _normalize_result(value: str | None) -> str:
    v = (value or "fail").lower()
    return v if v in ("pass", "fail", "unknown") else "fail"


def _load_results_from_answers_json(
    session_id: UUID,
    session_url: str,
) -> dict[int, str]:
    """
    Fallback: load AI grades from answers.json artifacts when DB results are missing.
    """
    config = get_config()
    artifacts_root = Path(config.artifacts_dir)
    domain = urlparse(session_url or "").netloc.replace("www.", "")
    root = artifacts_root / f"{domain}__{session_id}"
    if not root.exists():
        return {}

    priority = {"fail": 2, "unknown": 1, "pass": 0}
    grades: dict[int, str] = {}
    seen: dict[int, int] = {}

    for answers_path in root.rglob("answers.json"):
        try:
            data = json.loads(answers_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        results = data.get("results") or {}
        for key, value in results.items():
            try:
                qid = int(key)
            except (TypeError, ValueError):
                continue
            grade = _normalize_result((value or {}).get("result"))
            p = priority.get(grade, -1)
            prev = seen.get(qid, -1)
            if p > prev:
                seen[qid] = p
                grades[qid] = grade
    return grades


def _load_rubric_questions(
    repository: AuditRepository,
    session_id: UUID,
) -> list[dict[str, Any]]:
    """
    Load rubric questions from the canonical questions table.

    For now this uses list_questions without filters and maps fields into the
    structure required for the Questions sheet and Output mapping.
    """
    questions = repository.list_questions()

    session_data = repository.get_session_by_id(session_id)
    ai_grade_by_question_id: dict[int, str] = {}
    if session_data is not None:
        domain = urlparse(session_data.get("url", "")).netloc.replace("www.", "")
        session_id_str = f"{domain}__{session_id}"
        results = repository.get_audit_results_by_session_id(session_id_str)
        priority = {"fail": 2, "unknown": 1, "pass": 0}
        seen: dict[int, int] = {}
        for res in results:
            qid = res.get("question_id")
            if qid is None:
                continue
            grade = _normalize_result(res.get("result"))
            p = priority.get(grade, -1)
            prev = seen.get(qid, -1)
            if p > prev:
                seen[qid] = p
                ai_grade_by_question_id[qid] = grade

        if not ai_grade_by_question_id:
            ai_grade_by_question_id = _load_results_from_answers_json(
                session_id,
                session_data.get("url", ""),
            )
    mapped: list[dict[str, Any]] = []
    mapped_raw: list[dict[str, Any]] = []
    for q in questions:
        qid = q.get("question_id")
        ai_grade = ai_grade_by_question_id.get(qid, "")
        mapped_raw.append(
            {
                "category": q.get("category") or "",
                "question": q.get("question") or "",
                "ai_grade": ai_grade,
                "tier": q.get("tier"),
                "severity": q.get("severity"),
                "page_type": q.get("page_type") or "",
                "bar_chart_category": q.get("bar_chart_category") or "",
                "exact_fix": q.get("exact_fix") or "",
            }
        )

    tier1 = [q for q in mapped_raw if q["tier"] == 1]
    tier2 = [q for q in mapped_raw if q["tier"] == 2]
    tier3 = [q for q in mapped_raw if q["tier"] == 3]

    def _not_pass(rows: list[dict[str, Any]]) -> bool:
        return any(_normalize_result(r["ai_grade"]) != "pass" for r in rows)

    if tier1 and _not_pass(tier1):
        included = tier1
    elif tier1 and tier2 and _not_pass(tier2):
        included = tier1 + tier2
    else:
        included = mapped_raw

    return included


def _build_artifact_index(artifacts: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, str]]:
    """
    Build an index: (page_type, viewport, artifact_type) -> storage_uri.
    """
    index: dict[tuple[str, str, str], dict[str, str]] = {}
    for art in artifacts:
        page_id = art.get("page_id")
        if page_id is None:
            continue
        art_type = art.get("type")
        storage_uri = art.get("storage_uri")
        index.setdefault((str(page_id), art_type, ""), {})
        index[(str(page_id), art_type, "")]["uri"] = storage_uri
    return index


def _build_page_index(pages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Build an index: page_id -> page dict.
    """
    return {str(p["id"]): p for p in pages}


def _create_workbook_for_session(
    repository: AuditRepository,
    session_id: UUID,
) -> bytes:
    """
    Create an Excel workbook with Questions and Output sheets for a session.
    """
    questions = _load_rubric_questions(repository, session_id)
    questions = sorted(questions, key=lambda q: (q["category"], q["question"]))

    wb = Workbook()
    # Default sheet becomes Questions
    questions_ws = wb.active
    questions_ws.title = "Questions"
    output_ws = wb.create_sheet(title="Output")

    # Questions header
    questions_ws.append(QUESTIONS_HEADERS)
    for q in questions:
        questions_ws.append(
            [
                q["category"],
                q["question"],
                q["ai_grade"],
                "",
                q["tier"],
                q["severity"],
                q["page_type"],
                q["bar_chart_category"],
                q["exact_fix"],
            ]
        )

    # Output header
    output_ws.append(OUTPUT_HEADERS)

    # Output rows: one per question, sorted by category, with empty AI grade placeholder.
    for q in questions:
        output_ws.append(
            [
                q["category"],
                q["question"],
                q["ai_grade"],
            ]
        )

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def save_excel_rubric_workbook(
    repository: AuditRepository,
    session_id: UUID,
    domain: str,
) -> bool:
    """
    Generate and save a session-level Excel rubric workbook for the given session.

    Creates a session-level artifact (page_id=None) of type excel_rubric_xlsx at
    {domain}__{session_id}/output.xlsx. On failure, logs an error and returns False.
    """
    try:
        logger.info(
            "excel_rubric_generation_started",
            session_id=str(session_id),
            domain=domain,
        )
        workbook_bytes = _create_workbook_for_session(repository, session_id)
        path = build_excel_rubric_artifact_path(domain, session_id)
        size, checksum = write_binary(path, workbook_bytes)
        storage_uri = get_storage_uri(path)
        repository.create_artifact(
            session_id=session_id,
            page_id=None,
            artifact_type="excel_rubric_xlsx",
            storage_uri=storage_uri,
            size_bytes=size,
            retention_until=None,
            checksum=checksum,
        )
        logger.info(
            "excel_rubric_artifact_saved",
            session_id=str(session_id),
            domain=domain,
            storage_uri=storage_uri,
            size_bytes=size,
        )
        return True
    except Exception as exc:
        logger.error(
            "excel_rubric_generation_failed",
            session_id=str(session_id),
            domain=domain,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="artifact",
            message="Excel rubric workbook generation failed",
            details={
                "artifact_type": "excel_rubric_xlsx",
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        )
        return False

