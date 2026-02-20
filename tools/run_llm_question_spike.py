#!/usr/bin/env python3
"""
Run a question-evaluation LLM spike from a prepared payload JSON file.

Usage:
  python tools/run_llm_question_spike.py \
    --payload artifacts/<session>/llm_question_payload_spike_test.json

By default this sends one request per question and writes
`llm_question_spike_results.json` next to the payload.
Use --dry-run to validate payload wiring without calling the LLM API.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_output_text(resp: Any) -> str:
    text = getattr(resp, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    output = getattr(resp, "output", None)
    try:
        if output and len(output) > 0:
            content = output[0].content
            if content and len(content) > 0:
                inner = content[0]
                inner_text = getattr(inner, "text", None)
                if isinstance(inner_text, str) and inner_text.strip():
                    return inner_text.strip()
    except Exception:
        pass
    return str(resp).strip()


def _collect_image_paths(node: Any) -> list[str]:
    out: list[str] = []

    def _walk(n: Any) -> None:
        if isinstance(n, dict):
            for k, v in n.items():
                if isinstance(v, str) and k.endswith("_path") and v.lower().endswith(".png"):
                    out.append(v)
                else:
                    _walk(v)
        elif isinstance(n, list):
            for item in n:
                _walk(item)

    _walk(node)
    # Keep deterministic order while de-duping.
    return list(dict.fromkeys(out))


def _question_requires_screenshot(question: dict[str, Any]) -> bool:
    primary = str(question.get("primary_payload") or "").strip().lower()
    secondary = str(question.get("secondary_payload") or "").strip().lower()
    return primary == "screenshot" or secondary == "screenshot"


def _read_visible_text_snippet(question: dict[str, Any], max_chars: int = 3000) -> dict[str, str]:
    snippets: dict[str, str] = {}
    evidence = question.get("evidence", {})
    for device in ("desktop", "mobile", "cart_desktop", "checkout_desktop"):
        node = evidence.get(device)
        if not isinstance(node, dict):
            continue
        p = node.get("visible_text_path")
        if not isinstance(p, str):
            continue
        path = Path(p)
        if not path.exists():
            continue
        txt = path.read_text(encoding="utf-8", errors="ignore")
        snippets[device] = txt[:max_chars]
    return snippets


def _build_prompt_text(
    payload: dict[str, Any],
    question: dict[str, Any],
    text_snippets: dict[str, str],
) -> str:
    contract = payload.get("llm_contract", {})
    expected_fields = contract.get("expected_output_fields", [])
    rubric_text = question.get("ai_instruction") or question.get("instructions") or ""
    return (
        "You are evaluating one ecommerce audit question.\n"
        "Return JSON only. No markdown. No extra text.\n\n"
        "Decision rules:\n"
        f"- default_if_unclear: {contract.get('default_if_unclear', 'fail')}\n"
        f"- device_consistency_required: {contract.get('device_consistency_required', True)}\n\n"
        "Output type rules:\n"
        '- "pass_fail" MUST be a boolean: true or false (never "pass"/"fail" strings).\n'
        '- "score_1_to_10" MUST be integer 1..10.\n'
        '- "ai_confidence_1_to_10" MUST be integer 1..10.\n\n'
        "Required output fields:\n"
        f"{json.dumps(expected_fields, ensure_ascii=False)}\n\n"
        "Full rubric/instructions:\n"
        f"{rubric_text}\n\n"
        "Question payload:\n"
        f"{json.dumps(question, ensure_ascii=False)}\n\n"
        "Visible text snippets (truncated):\n"
        f"{json.dumps(text_snippets, ensure_ascii=False)}\n"
    )


def _validate_result(required_fields: list[str], result: dict[str, Any]) -> list[str]:
    missing = [k for k in required_fields if k not in result]
    errs: list[str] = []
    if missing:
        errs.append(f"missing_fields: {missing}")
    if "pass_fail" in result and not isinstance(result["pass_fail"], bool):
        errs.append("pass_fail must be boolean")
    if "score_1_to_10" in result and not isinstance(result["score_1_to_10"], int):
        errs.append("score_1_to_10 must be integer")
    if "ai_confidence_1_to_10" in result and not isinstance(result["ai_confidence_1_to_10"], int):
        errs.append("ai_confidence_1_to_10 must be integer")
    return errs


def _normalize_result(parsed: dict[str, Any]) -> dict[str, Any]:
    out = dict(parsed)
    pf = out.get("pass_fail")
    if isinstance(pf, str):
        pf_norm = pf.strip().lower()
        if pf_norm == "pass":
            out["pass_fail"] = True
        elif pf_norm == "fail":
            out["pass_fail"] = False
    return out


def _call_question(
    client: OpenAI,
    model: str,
    payload: dict[str, Any],
    question: dict[str, Any],
) -> dict[str, Any]:
    required_fields = payload.get("llm_contract", {}).get("expected_output_fields", [])
    snippets = _read_visible_text_snippet(question)
    prompt = _build_prompt_text(payload, question, snippets)

    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    image_paths: list[str] = []
    if _question_requires_screenshot(question):
        image_paths = _collect_image_paths(question.get("evidence", {}))

    attached_images: list[str] = []
    for image_path in image_paths:
        path = Path(image_path)
        if not path.exists():
            continue
        raw = path.read_bytes()
        data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        content.append({"type": "input_image", "image_url": data_url})
        attached_images.append(str(path))

    resp = client.responses.create(
        model=model,
        input=[{"role": "user", "content": content}],
        text={"format": {"type": "json_object"}},
    )

    raw = _extract_output_text(resp)
    parsed: dict[str, Any] | None = None
    parse_error: str | None = None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed = _normalize_result(parsed)
    except Exception as exc:
        parse_error = str(exc)

    validation_errors: list[str] = []
    if parsed is not None:
        validation_errors = _validate_result(required_fields, parsed)

    return {
        "question_sheet_row": question.get("sheet_row"),
        "question_text": question.get("question_text"),
        "primary_payload": question.get("primary_payload"),
        "secondary_payload": question.get("secondary_payload"),
        "attached_images": attached_images,
        "raw_response_text": raw,
        "parsed_result": parsed,
        "parse_error": parse_error,
        "validation_errors": validation_errors,
    }


def run_spike(payload_path: Path, output_path: Path, model: str, dry_run: bool) -> None:
    payload = _load_json(payload_path)
    questions = payload.get("questions_for_spike", [])
    if not isinstance(questions, list) or not questions:
        raise ValueError("Payload has no questions_for_spike")

    out: dict[str, Any] = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "payload_path": str(payload_path),
        "model": model,
        "dry_run": dry_run,
        "question_count": len(questions),
        "results": [],
    }

    if dry_run:
        for q in questions:
            out["results"].append(
                {
                    "question_sheet_row": q.get("sheet_row"),
                    "question_text": q.get("question_text"),
                    "primary_payload": q.get("primary_payload"),
                    "secondary_payload": q.get("secondary_payload"),
                    "attached_images_preview": (
                        _collect_image_paths(q.get("evidence", {}))
                        if _question_requires_screenshot(q)
                        else []
                    ),
                    "visible_text_snippets_present": list(_read_visible_text_snippet(q).keys()),
                }
            )
        output_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        return

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for non-dry-run mode")
    client = OpenAI(api_key=api_key)

    for idx, question in enumerate(questions, start=1):
        print(f"[{idx}/{len(questions)}] Evaluating row {question.get('sheet_row')}")
        result = _call_question(client, model, payload, question)
        out["results"].append(result)

    output_path.write_text(json.dumps(out, indent=2), encoding="utf-8")


def main() -> None:
    # Load .env from repository root so OPENAI_API_KEY is available in local runs.
    repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / ".env")
    # Also allow default discovery for callers running from different working dirs.
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run LLM question-evaluation spike")
    parser.add_argument(
        "--payload",
        required=True,
        help="Path to llm_question_payload_spike_test.json",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for spike results JSON (default: next to payload)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("QUESTION_EVAL_MODEL", os.getenv("HTML_ANALYSIS_MODEL", "gpt-4o-mini")),
        help="Model name for Responses API",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate payload and write preview output without LLM API calls",
    )
    args = parser.parse_args()

    payload_path = Path(args.payload)
    if not payload_path.exists():
        raise FileNotFoundError(f"Payload file not found: {payload_path}")

    output_path = (
        Path(args.output)
        if args.output
        else payload_path.parent / "llm_question_spike_results.json"
    )

    run_spike(payload_path, output_path, args.model, args.dry_run)
    print(f"Results written: {output_path}")


if __name__ == "__main__":
    main()
