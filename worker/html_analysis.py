"""
HTML analysis using ChatGPT API for product page form and variant detection.

Analyzes product page HTML to identify purchase forms, variant groups, and add-to-cart buttons.

Supports two modes:
- automatic: Uses OpenAI API directly
- manual: Prints HTML file path, waits for user to upload manually, then prompts for JSON result
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional
from uuid import UUID

from openai import OpenAI

from shared.config import get_config
from shared.logging import get_logger
from worker.repository import AuditRepository
from worker.storage import ensure_artifact_dir, get_storage_uri, write_json

logger = get_logger(__name__)


def analyze_product_html(
    html_content: str,
    session_id: UUID,
    page_id: UUID,
    page_type: str,
    viewport: str,
    domain: str,
    repository: AuditRepository,
) -> Optional[dict]:
    """
    Analyze product page HTML using ChatGPT API to identify forms, variants, and add-to-cart.

    Supports manual and automatic modes controlled by HTML_ANALYSIS_MODE env var.
    Returns the analysis JSON dict, or None on failure.

    For mobile viewport, reuses JSON from desktop if it exists to avoid duplicate API calls.
    """
    if page_type not in ("product", "pdp"):
        logger.info("html_analysis_skipped", reason="not_product_page", page_type=page_type)
        return None

    storage_page_type = "pdp" if page_type == "product" else page_type
    config = get_config()

    artifacts_root = Path(config.artifacts_dir)
    normalized_domain = (domain or "").strip().lower()
    if normalized_domain.startswith("www."):
        normalized_domain = normalized_domain[4:]
    normalized_domain = normalized_domain or "unknown-domain"
    root_name = f"{normalized_domain}__{session_id}"

    shared_analysis_path = artifacts_root / root_name / storage_page_type / "html_analysis.json"

    if viewport == "mobile" and shared_analysis_path.exists():
        logger.info(
            "html_analysis_reusing_desktop_json",
            session_id=str(session_id),
            viewport=viewport,
            shared_path=str(shared_analysis_path),
        )
        try:
            with open(shared_analysis_path, "r", encoding="utf-8") as f:
                analysis_json = json.load(f)
            analysis_json["_file_path"] = str(shared_analysis_path.absolute())
            logger.info(
                "html_analysis_reused_successfully",
                session_id=str(session_id),
                viewport=viewport,
            )
            return analysis_json
        except Exception as e:
            logger.warning(
                "html_analysis_reuse_failed",
                error=str(e),
                session_id=str(session_id),
                viewport=viewport,
            )

    mode = config.html_analysis_mode.lower()

    if mode == "manual":
        return _analyze_manual_mode(
            html_content,
            session_id,
            page_id,
            storage_page_type,
            viewport,
            domain,
            repository,
            shared_analysis_path,
        )
    else:
        return _analyze_automatic_mode(
            html_content,
            session_id,
            page_id,
            storage_page_type,
            viewport,
            domain,
            repository,
            shared_analysis_path,
        )


def _analyze_manual_mode(
    html_content: str,
    session_id: UUID,
    page_id: UUID,
    page_type: str,
    viewport: str,
    domain: str,
    repository: AuditRepository,
    shared_analysis_path: Path,
) -> Optional[dict]:
    """Manual mode: print HTML file path, wait for user input, then prompt for JSON result."""
    try:
        config = get_config()
        artifacts_root = Path(config.artifacts_dir)
        normalized_domain = (domain or "").strip().lower()
        if normalized_domain.startswith("www."):
            normalized_domain = normalized_domain[4:]
        normalized_domain = normalized_domain or "unknown-domain"
        root_name = f"{normalized_domain}__{session_id}"
        html_file_path = (
            artifacts_root / root_name / page_type / viewport / "html_for_analysis.html"
        )

        ensure_artifact_dir(html_file_path)
        html_file_path.write_text(html_content, encoding="utf-8")

        analysis_path = shared_analysis_path

        config = get_config()
        if config.telegram_bot_token and config.telegram_chat_id:
            try:
                from shared.telegram import send_telegram_message

                prompt_path = Path(__file__).parent.parent / "promp.txt"
                prompt_preview = ""
                if prompt_path.exists():
                    with open(prompt_path, "r", encoding="utf-8") as f:
                        prompt_content = f.read()
                        preview_text = prompt_content[:300]
                        prompt_preview = (
                            f"\n\n📋 <b>Prompt preview (first 300 chars):</b>\n"
                            f"<pre>{preview_text}...</pre>"
                        )

                message = f"""🔍 <b>HTML Analysis Required - Manual Mode</b>

📄 <b>Domain:</b> {domain}
🆔 <b>Session:</b> {str(session_id)[:8]}...

📁 <b>HTML file saved at:</b>
<code>{html_file_path.absolute()}</code>

📋 <b>Expected JSON file:</b>
<code>{analysis_path.absolute()}</code>

📝 <b>Instructions:</b>
1. Upload the HTML file to ChatGPT
2. Use the prompt from promp.txt
3. Save the JSON response to the path above

⏳ Waiting for JSON file...{prompt_preview}"""

                result = send_telegram_message(
                    bot_token=config.telegram_bot_token,
                    chat_id=config.telegram_chat_id,
                    message=message,
                    parse_mode="HTML",
                )
                if result:
                    logger.info("telegram_notification_sent", session_id=str(session_id))
                else:
                    logger.warning("telegram_notification_failed", session_id=str(session_id))
            except Exception as e:
                logger.warning(
                    "telegram_notification_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    session_id=str(session_id),
                )

        print("\n" + "=" * 80)
        print("HTML ANALYSIS - MANUAL MODE")
        print("=" * 80)
        print("\nHTML file saved at:")
        print(f"  {html_file_path.absolute()}")
        print("\nExpected JSON output file:")
        print(f"  {analysis_path.absolute()}")
        print("\nPlease:")
        print("  1. Upload the HTML file to ChatGPT")
        print("  2. Use the prompt from: promp.txt")
        print("  3. Save the JSON response to:")
        print(f"     {analysis_path.absolute()}")
        print("\nWaiting for JSON file to be created...")
        print("(The process will continue automatically when the file exists)")
        sys.stdout.flush()

        import time

        max_wait_seconds = 3600
        wait_interval = 2
        waited = 0

        while not analysis_path.exists():
            if waited >= max_wait_seconds:
                logger.error("html_analysis_manual_timeout")
                print(f"\nERROR: Timeout after {max_wait_seconds} seconds waiting for JSON file")
                return None
            time.sleep(wait_interval)
            waited += wait_interval
            if waited % 30 == 0:
                print(f"Still waiting... ({waited}s elapsed)")
                sys.stdout.flush()

        print(f"\n✓ JSON file found! Reading: {analysis_path.absolute()}")
        sys.stdout.flush()

        with open(analysis_path, "r", encoding="utf-8") as f:
            analysis_json = json.load(f)

        config = get_config()
        if config.telegram_bot_token and config.telegram_chat_id:
            try:
                from shared.telegram import send_telegram_json

                send_telegram_json(
                    bot_token=config.telegram_bot_token,
                    chat_id=config.telegram_chat_id,
                    title=f"✅ ChatGPT Response Received - {domain}",
                    data=analysis_json,
                )
            except Exception as e:
                logger.warning("telegram_json_notification_failed", error=str(e))

        ensure_artifact_dir(analysis_path)
        size, checksum = write_json(analysis_path, analysis_json)
        storage_uri = get_storage_uri(analysis_path)

        repository.create_artifact(
            session_id=session_id,
            page_id=page_id,
            artifact_type="html_analysis_json",
            storage_uri=storage_uri,
            size_bytes=size,
            checksum=checksum,
        )

        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="html_analysis",
            message="HTML analysis completed (manual mode)",
            details={
                "mode": "manual",
                "size_bytes": size,
                "checksum": checksum,
                "storage_uri": storage_uri,
                "has_variants": analysis_json.get("has_variants", False),
                "form_found": analysis_json.get("form", {}).get("found", False),
            },
        )

        logger.info(
            "html_analysis_completed_manual",
            session_id=str(session_id),
            page_id=str(page_id),
            size_bytes=size,
            checksum=checksum,
            storage_uri=storage_uri,
        )

        print(f"\n✓ Analysis saved to: {analysis_path.absolute()}")
        print("=" * 80 + "\n")

        analysis_json["_file_path"] = str(analysis_path.absolute())
        return analysis_json

    except json.JSONDecodeError as e:
        logger.error(
            "html_analysis_manual_json_decode_failed",
            error=str(e),
            session_id=str(session_id),
            page_id=str(page_id),
        )
        print(f"\nERROR: Invalid JSON - {str(e)}")
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="html_analysis",
            message="HTML analysis JSON decode failed (manual mode)",
            details={"error": str(e), "error_type": type(e).__name__},
        )
        return None

    except Exception as e:
        logger.error(
            "html_analysis_manual_failed",
            error=str(e),
            error_type=type(e).__name__,
            session_id=str(session_id),
            page_id=str(page_id),
        )
        print(f"\nERROR: {str(e)}")
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="html_analysis",
            message="HTML analysis failed (manual mode)",
            details={"error": str(e), "error_type": type(e).__name__},
        )
        return None


def _analyze_automatic_mode(
    html_content: str,
    session_id: UUID,
    page_id: UUID,
    page_type: str,
    viewport: str,
    domain: str,
    repository: AuditRepository,
    shared_analysis_path: Path,
) -> Optional[dict]:
    """Automatic mode: use OpenAI Responses API with chunked HTML and JSON-only output."""
    try:
        prompt_path = Path(__file__).parent.parent / "promp.txt"
        if not prompt_path.exists():
            logger.error("prompt_file_not_found", path=str(prompt_path))
            return None

        with open(prompt_path, "r", encoding="utf-8") as f:
            base_prompt = f.read().strip()

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("openai_api_key_missing")
            repository.create_log(
                session_id=session_id,
                level="error",
                event_type="html_analysis",
                message="OpenAI API key not configured",
                details={"error": "OPENAI_API_KEY environment variable not set"},
            )
            return None

        client = OpenAI(api_key=api_key)

        logger.info(
            "html_analysis_started",
            session_id=str(session_id),
            page_id=str(page_id),
            viewport=viewport,
        )

        config = get_config()
        telegram_bot_token = getattr(config, "telegram_bot_token", None)
        telegram_chat_id = getattr(config, "telegram_chat_id", None)
        telegram_enabled = bool(telegram_bot_token and telegram_chat_id)

        model_name = os.getenv("HTML_ANALYSIS_MODEL", "gpt-5.2")

        if telegram_enabled:
            try:
                from shared.telegram import send_telegram_message

                send_telegram_message(
                    bot_token=telegram_bot_token,
                    chat_id=telegram_chat_id,
                    message=(
                        "1. Preparing HTML analysis (automatic mode)\n"
                        f"Domain: {domain}\n"
                        f"Session: {session_id}\n"
                        f"Viewport: {viewport}\n"
                        f"Model: {model_name}"
                    ),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning("telegram_step_notification_failed", step="prepare", error=str(e))

        def _chunk_text(s: str, chunk_chars: int) -> list[str]:
            return [s[i : i + chunk_chars] for i in range(0, len(s), chunk_chars)]

        def _extract_output_text(resp) -> str:
            text = getattr(resp, "output_text", None)
            if isinstance(text, str) and text.strip():
                return text.strip()
            out = getattr(resp, "output", None)
            try:
                if out and len(out) > 0:
                    content = out[0].content
                    if content and len(content) > 0:
                        inner = content[0]
                        inner_text = getattr(inner, "text", None)
                        if isinstance(inner_text, str) and inner_text.strip():
                            return inner_text.strip()
            except Exception:
                pass
            return str(resp).strip()

        def _call_json_only(user_text: str) -> Optional[dict]:
            """Call Responses API and force JSON-only output with one retry."""
            for attempt in (1, 2):
                resp = client.responses.create(
                    model=model_name,
                    input=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": user_text,
                                }
                            ],
                        }
                    ],
                    text={"format": {"type": "json_object"}},
                )
                raw = _extract_output_text(resp)
                try:
                    return json.loads(raw)
                except Exception:
                    if attempt == 1:
                        user_text = (
                            "Your previous response was NOT valid JSON.\n"
                            "Return ONLY valid JSON. No markdown, no code fences, no extra text.\n"
                            "Output must start with { or [ and end with } or ].\n\n" + user_text
                        )
                        continue
                    logger.error(
                        "html_analysis_json_decode_failed_partial",
                        session_id=str(session_id),
                        viewport=viewport,
                    )
                    return None
            return None

        html = html_content or ""
        if not html.strip():
            logger.error("html_analysis_empty_html")
            return None

        chunk_chars = int(os.getenv("HTML_ANALYSIS_CHUNK_CHARS", "80000"))
        max_chunks = int(os.getenv("HTML_ANALYSIS_MAX_CHUNKS", "25"))
        strategy = os.getenv("HTML_ANALYSIS_CHUNK_STRATEGY", "all")

        chunks = _chunk_text(html, chunk_chars)
        total_chunks = len(chunks)

        if strategy == "head":
            selected = chunks[:1]
        elif strategy == "all":
            selected = chunks
        else:
            selected = chunks[:1] + (chunks[-1:] if len(chunks) > 1 else [])

        if len(selected) > max_chunks:
            selected = selected[:max_chunks]

        logger.info(
            "html_chunking_config",
            total_chunks=total_chunks,
            selected_chunks=len(selected),
            chunk_chars=chunk_chars,
            strategy=strategy,
        )

        if telegram_enabled:
            try:
                from shared.telegram import send_telegram_message

                send_telegram_message(
                    bot_token=telegram_bot_token,
                    chat_id=telegram_chat_id,
                    message=(
                        "2. Sending HTML chunks to OpenAI (automatic mode)\n"
                        f"Domain: {domain}\n"
                        f"Session: {session_id}\n"
                        f"Viewport: {viewport}\n"
                        f"Model: {model_name}\n"
                        f"Chunks: {len(selected)} of {total_chunks}"
                    ),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning(
                    "telegram_step_notification_failed", step="send_chunks", error=str(e)
                )

        partials: list[dict] = []
        for idx, ch in enumerate(selected, start=1):
            user_text = (
                base_prompt
                + "\n\n"
                + "IMPORTANT: You are receiving only a PARTIAL CHUNK of the full HTML.\n"
                + "Extract whatever you can FROM THIS CHUNK ONLY. If unknown, leave null/empty.\n"
                + f"CHUNK {idx} of {len(selected)}\n"
                + "RAW HTML CHUNK:\n"
                + ch
            )
            part = _call_json_only(user_text)
            if isinstance(part, dict):
                part["_chunk_index"] = idx
                part["_chunk_total"] = len(selected)
                partials.append(part)

        if not partials:
            logger.error("html_analysis_no_partials_generated")
            return None

        consolidate_text = (
            base_prompt
            + "\n\n"
            + "Now you will receive multiple PARTIAL JSON outputs from separate HTML chunks.\n"
            + "Merge them into ONE final JSON that matches the OUTPUT schema EXACTLY.\n"
            + "Rules:\n"
            + "- Return JSON ONLY.\n"
            + "- Prefer selectors scoped to the purchase form.\n"
            + "- Deduplicate variant groups/options.\n"
            + "- If conflicts, prefer the most specific/stable selectors.\n\n"
            + "PARTIAL_JSON_LIST:\n"
            + json.dumps(partials, ensure_ascii=False)
        )

        analysis_json = _call_json_only(consolidate_text)
        if not isinstance(analysis_json, dict):
            logger.error("html_analysis_consolidation_failed")
            return None

        if telegram_enabled:
            try:
                from shared.telegram import send_telegram_json, send_telegram_message

                send_telegram_message(
                    bot_token=telegram_bot_token,
                    chat_id=telegram_chat_id,
                    message=(
                        "3. OpenAI response received (automatic mode)\n"
                        f"Domain: {domain}\n"
                        f"Session: {session_id}\n"
                        f"Viewport: {viewport}"
                    ),
                    parse_mode="HTML",
                )

                send_telegram_json(
                    bot_token=telegram_bot_token,
                    chat_id=telegram_chat_id,
                    title=f"ChatGPT Response - {domain}",
                    data=analysis_json,
                )
            except Exception as e:
                logger.warning("telegram_notification_failed", error=str(e))

        analysis_path = shared_analysis_path
        ensure_artifact_dir(analysis_path)
        size, checksum = write_json(analysis_path, analysis_json)
        storage_uri = get_storage_uri(analysis_path)

        repository.create_artifact(
            session_id=session_id,
            page_id=page_id,
            artifact_type="html_analysis_json",
            storage_uri=storage_uri,
            size_bytes=size,
            checksum=checksum,
        )

        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="html_analysis",
            message="HTML analysis completed (automatic mode)",
            details={
                "mode": "automatic",
                "size_bytes": size,
                "checksum": checksum,
                "storage_uri": storage_uri,
                "has_variants": analysis_json.get("has_variants", False),
                "form_found": analysis_json.get("form", {}).get("found", False),
            },
        )

        logger.info(
            "html_analysis_completed_automatic",
            session_id=str(session_id),
            page_id=str(page_id),
            size_bytes=size,
            checksum=checksum,
            storage_uri=storage_uri,
        )

        analysis_json["_file_path"] = str(analysis_path.absolute())
        return analysis_json

    except Exception as e:
        logger.error(
            "html_analysis_failed",
            error=str(e),
            error_type=type(e).__name__,
            session_id=str(session_id),
            page_id=str(page_id),
        )
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="html_analysis",
            message="HTML analysis failed",
            details={"error": str(e), "error_type": type(e).__name__},
        )
        return None
