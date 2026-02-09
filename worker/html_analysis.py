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
            html_content, session_id, page_id, storage_page_type, viewport, domain, repository, shared_analysis_path
        )
    else:
        return _analyze_automatic_mode(
            html_content, session_id, page_id, storage_page_type, viewport, domain, repository, shared_analysis_path
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
        flag_file = analysis_path.parent / "html_analysis_ready.flag"

        config = get_config()
        if config.telegram_bot_token and config.telegram_chat_id:
            try:
                from shared.telegram import send_telegram_message
                
                prompt_path = Path(__file__).parent.parent / "promp.txt"
                prompt_preview = ""
                if prompt_path.exists():
                    with open(prompt_path, "r", encoding="utf-8") as f:
                        prompt_content = f.read()
                        prompt_preview = f"\n\n📋 <b>Prompt preview (first 300 chars):</b>\n<pre>{prompt_content[:300]}...</pre>"
                
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
                logger.warning("telegram_notification_failed", error=str(e), error_type=type(e).__name__, session_id=str(session_id))

        print("\n" + "=" * 80)
        print("HTML ANALYSIS - MANUAL MODE")
        print("=" * 80)
        print(f"\nHTML file saved at:")
        print(f"  {html_file_path.absolute()}")
        print(f"\nExpected JSON output file:")
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
    """Automatic mode: use OpenAI API with file upload."""
    try:
        prompt_path = Path(__file__).parent.parent / "promp.txt"
        if not prompt_path.exists():
            logger.error("prompt_file_not_found", path=str(prompt_path))
            return None

        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()

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

        logger.info("html_analysis_started", session_id=str(session_id), page_id=str(page_id), viewport=viewport)

        temp_html_file = shared_analysis_path.parent / f"temp_html_{session_id}_{viewport}.html"
        ensure_artifact_dir(temp_html_file)
        temp_html_file.write_text(html_content, encoding="utf-8")

        uploaded_file = None
        assistant = None
        response_text = None

        try:
            logger.info("uploading_html_file", file_path=str(temp_html_file), session_id=str(session_id))
            
            with open(temp_html_file, "rb") as f:
                uploaded_file = client.files.create(
                    file=f,
                    purpose="assistants"
                )
            
            logger.info("html_file_uploaded", file_id=uploaded_file.id, session_id=str(session_id))

            assistant = client.beta.assistants.create(
                name="HTML Analysis Assistant",
                instructions="You are an HTML analysis engine. Return ONLY valid JSON, no markdown, no explanations.",
                model="gpt-4o",
                tools=[{"type": "code_interpreter"}],
            )

            thread = client.beta.threads.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt_template,
                        "attachments": [
                            {
                                "file_id": uploaded_file.id,
                                "tools": [{"type": "code_interpreter"}]
                            }
                        ]
                    }
                ]
            )

            run = client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=assistant.id,
            )

            import time
            max_wait = 300
            waited = 0
            while run.status in ["queued", "in_progress"]:
                if waited >= max_wait:
                    raise TimeoutError("Assistant run timed out")
                time.sleep(2)
                waited += 2
                run = client.beta.threads.runs.retrieve(
                    thread_id=thread.id,
                    run_id=run.id
                )

            if run.status != "completed":
                raise Exception(f"Assistant run failed with status: {run.status}")

            messages = client.beta.threads.messages.list(thread_id=thread.id)
            
            response_text = None
            for message in messages.data:
                if message.role == "assistant":
                    for content_item in message.content:
                        if hasattr(content_item, 'text') and hasattr(content_item.text, 'value'):
                            response_text = content_item.text.value
                            break
                    if response_text:
                        break
            
            if not response_text:
                logger.error(
                    "html_analysis_no_assistant_response",
                    session_id=str(session_id),
                    message_count=len(messages.data),
                    message_roles=[msg.role for msg in messages.data]
                )
                raise Exception("No assistant response found in messages")

        finally:
            if assistant:
                try:
                    client.beta.assistants.delete(assistant.id)
                    logger.info("assistant_deleted", assistant_id=assistant.id, session_id=str(session_id))
                except Exception as e:
                    logger.warning("assistant_delete_failed", error=str(e), session_id=str(session_id))
            
            if uploaded_file:
                try:
                    client.files.delete(uploaded_file.id)
                    logger.info("temp_file_deleted", file_id=uploaded_file.id, session_id=str(session_id))
                except Exception as e:
                    logger.warning("temp_file_delete_failed", error=str(e), session_id=str(session_id))
            
            try:
                if temp_html_file.exists():
                    temp_html_file.unlink()
            except Exception as e:
                logger.warning("local_temp_file_delete_failed", error=str(e), session_id=str(session_id))

        if not response_text:
            logger.error("html_analysis_empty_response")
            return None

        analysis_json = json.loads(response_text)
        
        config = get_config()
        if config.telegram_bot_token and config.telegram_chat_id:
            try:
                from shared.telegram import send_telegram_json
                send_telegram_json(
                    bot_token=config.telegram_bot_token,
                    chat_id=config.telegram_chat_id,
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

    except json.JSONDecodeError as e:
        logger.error(
            "html_analysis_json_decode_failed",
            error=str(e),
            session_id=str(session_id),
            page_id=str(page_id),
        )
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="html_analysis",
            message="HTML analysis JSON decode failed",
            details={"error": str(e), "error_type": type(e).__name__},
        )
        return None

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
