#!/usr/bin/env python3
"""
Build report template data from artifact answers.

This script starts from a base report data JSON (typically templates/sample_data.json),
maps PASS/FAIL answers from artifact page answers.json files into the audit tables,
and recomputes phase summary metrics used by the PDF template.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
DEFAULT_BASE_DATA = TEMPLATES_DIR / "sample_data.json"

logger = logging.getLogger(__name__)

PHASE_CONFIG = {
    "awareness": ("homepage",),
    "consideration": ("pdp",),
    "conversion": ("cart", "checkout"),
}

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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _tokenize(text: str) -> set[str]:
    clean = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return {t for t in clean.split() if len(t) > 2 and t not in STOPWORDS}


def _similarity(row_text: str, reason: str) -> float:
    row = row_text.lower()
    src = reason.lower()
    if row in src:
        return 1.0

    row_tokens = _tokenize(row_text)
    src_tokens = _tokenize(reason)
    if not row_tokens or not src_tokens:
        return 0.0

    intersection = len(row_tokens & src_tokens)
    union = len(row_tokens | src_tokens)
    jaccard = intersection / union if union else 0.0
    coverage = intersection / len(row_tokens) if row_tokens else 0.0
    return 0.65 * coverage + 0.35 * jaccard


def _phase_rows(data: dict[str, Any], phase: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in data[phase]["audit_tables"]:
        rows.extend(table["rows"])
    return rows


def _collect_answers(session_root: Path) -> dict[str, dict[int, dict[str, Any]]]:
    out: dict[str, dict[int, dict[str, Any]]] = {}
    for page_type in ("homepage", "pdp", "cart", "checkout"):
        path = session_root / page_type / "answers.json"
        if not path.exists():
            logger.warning("answers_file_missing page_type=%s path=%s", page_type, path)
            continue
        payload = _load_json(path)
        results = payload.get("results", {})
        parsed: dict[int, dict[str, Any]] = {}
        for raw_qid, val in results.items():
            try:
                qid = int(raw_qid)
            except ValueError:
                continue
            parsed[qid] = val
        out[page_type] = parsed
    return out


def _set_phase_scores(data: dict[str, Any], phase: str, matched: int, passed: int) -> None:
    rating = data[phase]["rating"]
    failed = max(matched - passed, 0)
    overall = round((passed / matched) * 100) if matched else 0

    rating["overall_score"] = overall
    rating["max_score"] = 100
    rating["points_earned"] = passed
    rating["points_possible"] = matched
    rating["recommended_changes"] = failed
    rating["summary"] = (
        f"Analyzed {matched} touchpoints. "
        f"{passed} passed and {failed} failed. "
        "Use failed rows as highest-priority fixes."
    )

    for cat in rating.get("categories", []):
        cat["score"] = overall


def _update_performance_summary(data: dict[str, Any]) -> None:
    for phase in ("awareness", "consideration", "conversion"):
        score = data[phase]["rating"]["overall_score"]
        note = "Strong performance" if score >= 80 else "Needs focused improvements"
        data["performance_summary"][phase]["score"] = score
        data["performance_summary"][phase]["note"] = note


def _populate_change_log(data: dict[str, Any], failed_rows: list[str]) -> None:
    table = data.get("change_log_table", [])
    for idx, entry in enumerate(table):
        if idx < len(failed_rows):
            entry["item"] = failed_rows[idx]
            entry["impact"] = "High"
        else:
            entry["item"] = ""
            entry["impact"] = ""


def build_report_data(base_data: Path, session_root: Path) -> dict[str, Any]:
    data = copy.deepcopy(_load_json(base_data))
    answers = _collect_answers(session_root)

    all_failed_rows: list[str] = []

    for phase, page_types in PHASE_CONFIG.items():
        rows = _phase_rows(data, phase)
        used_rows: set[int] = set()
        matched = 0
        passed = 0

        phase_answers: list[tuple[int, dict[str, Any]]] = []
        for page_type in page_types:
            phase_answers.extend(sorted(answers.get(page_type, {}).items()))

        for qid, result in phase_answers:
            reason = str(result.get("reason", ""))
            outcome = str(result.get("result", "")).strip().upper()
            if outcome not in {"PASS", "FAIL"}:
                continue

            best_idx = -1
            best_score = 0.0
            for idx, row in enumerate(rows):
                if idx in used_rows:
                    continue
                score = _similarity(str(row.get("text", "")), reason)
                if score > best_score:
                    best_score = score
                    best_idx = idx

            if best_idx == -1 or best_score < 0.10:
                logger.info(
                    "answer_unmatched phase=%s question_id=%s score=%.3f",
                    phase,
                    qid,
                    best_score,
                )
                continue

            rows[best_idx]["pass"] = outcome == "PASS"
            used_rows.add(best_idx)
            matched += 1
            if outcome == "PASS":
                passed += 1
            else:
                all_failed_rows.append(rows[best_idx]["text"])

        _set_phase_scores(data, phase, matched, passed)
        logger.info(
            "phase_mapped phase=%s answers=%d matched=%d passed=%d failed=%d",
            phase,
            len(phase_answers),
            matched,
            passed,
            matched - passed,
        )

    _update_performance_summary(data)
    _populate_change_log(data, all_failed_rows)

    # Light metadata updates from session context.
    data["meta"]["site_url"] = session_root.name.split("__", 1)[0].replace("r_", "", 1)
    data["meta"]["report_date"] = datetime.now().strftime("%B %d, %Y")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build report JSON by overlaying artifact answers onto sample_data.json"
    )
    parser.add_argument(
        "--session-root",
        required=True,
        help="Artifact session root (e.g. artifacts/r_example.com__<uuid>)",
    )
    parser.add_argument(
        "--base-data",
        default=str(DEFAULT_BASE_DATA),
        help="Base report JSON (default: templates/sample_data.json)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output report data JSON path",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    report_data = build_report_data(Path(args.base_data), Path(args.session_root))
    _save_json(Path(args.output), report_data)
    logger.info("report_data_written path=%s", args.output)


if __name__ == "__main__":
    main()
