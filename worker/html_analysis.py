"""
HTML analysis using ChatGPT API for product page form and variant detection.

Analyzes product page HTML to identify purchase forms, variant groups, and add-to-cart buttons.

Supports two modes:
- automatic: Uses OpenAI API directly
- manual: Prints HTML file path, waits for user to upload manually, then prompts for JSON result
"""

from __future__ import annotations

import gzip
import json
import os
import re
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
    html_content: Optional[str],
    session_id: UUID,
    page_id: UUID,
    page_type: str,
    viewport: str,
    domain: str,
    repository: AuditRepository,
) -> Optional[dict]:
    """
    Analyze page HTML using ChatGPT API to identify forms, variants, and add-to-cart.

    Supports manual and automatic modes controlled by HTML_ANALYSIS_MODE env var.
    Returns the analysis JSON dict, or None on failure.

    For mobile viewport, reuses JSON from desktop if it exists to avoid duplicate API calls.

    Supports page types: pdp, product, cart, checkout

    If html_content is None, loads HTML from html_gz.html.gz file.
    """
    if page_type not in ("product", "pdp", "cart", "checkout"):
        logger.info("html_analysis_skipped", reason="unsupported_page_type", page_type=page_type)
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

    if html_content is None:
        html_gz_path = artifacts_root / root_name / storage_page_type / viewport / "html_gz.html.gz"
        if html_gz_path.exists():
            try:
                gz_size_bytes = html_gz_path.stat().st_size
                with gzip.open(html_gz_path, "rt", encoding="utf-8") as f:
                    html_content = f.read()
                html_chars = len(html_content)
                html_bytes = len(html_content.encode("utf-8"))
                logger.info(
                    "html_loaded_from_file",
                    path=str(html_gz_path),
                    gz_size_bytes=gz_size_bytes,
                    decompressed_chars=html_chars,
                    decompressed_bytes=html_bytes,
                    session_id=str(session_id),
                    page_type=page_type,
                    viewport=viewport,
                )
            except Exception as e:
                logger.error(
                    "html_load_failed",
                    path=str(html_gz_path),
                    error=str(e),
                    session_id=str(session_id),
                    page_type=page_type,
                )
                return None
        else:
            logger.warning(
                "html_file_not_found",
                path=str(html_gz_path),
                session_id=str(session_id),
                page_type=page_type,
                viewport=viewport,
            )
            return None

    if not html_content or not html_content.strip():
        logger.warning(
            "html_content_empty",
            session_id=str(session_id),
            page_type=page_type,
            viewport=viewport,
        )
        return None

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

        def _calculate_cost_usd(response, input_per_1m: float, output_per_1m: float):
            """Calculate estimated API cost from response usage."""
            if not hasattr(response, "usage") or not response.usage:
                return None

            usage = response.usage
            input_tokens = (
                getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None) or 0
            )
            output_tokens = (
                getattr(usage, "output_tokens", None)
                or getattr(usage, "completion_tokens", None)
                or 0
            )
            total_tokens = getattr(usage, "total_tokens", None) or (input_tokens + output_tokens)

            input_cost = (input_tokens / 1_000_000) * input_per_1m
            output_cost = (output_tokens / 1_000_000) * output_per_1m
            estimated_cost_usd = round(input_cost + output_cost, 6)

            return {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "estimated_cost_usd": estimated_cost_usd,
            }

        request_timeout = float(os.getenv("HTML_ANALYSIS_REQUEST_TIMEOUT_SEC", "120"))

        def _call_json_only(user_text: str) -> tuple[Optional[dict], Optional[dict]]:
            """Call Responses API, JSON-only output, one retry. Returns (json_dict, cost_data)."""
            input_per_1m = float(os.getenv("OPENAI_PRICE_INPUT_PER_1M", "0"))
            output_per_1m = float(os.getenv("OPENAI_PRICE_OUTPUT_PER_1M", "0"))

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
                    timeout=request_timeout,
                )
                raw = _extract_output_text(resp)
                cost_data = (
                    _calculate_cost_usd(resp, input_per_1m, output_per_1m)
                    if (input_per_1m > 0 or output_per_1m > 0)
                    else None
                )
                try:
                    return json.loads(raw), cost_data
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
                    return None, cost_data
            return None, None

        html = html_content or ""
        if not html.strip():
            logger.error("html_analysis_empty_html")
            return None

        use_single_request = os.getenv("HTML_ANALYSIS_SINGLE_REQUEST", "true").lower() == "true"
        max_html_chars = int(os.getenv("HTML_ANALYSIS_MAX_HTML_CHARS", "100000"))

        def strip_html_for_analysis(html: str) -> str:
            """Strip scripts, styles, and comments from HTML (same as audit evaluation)."""
            html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
            html = re.sub(
                r"<noscript[^>]*>.*?</noscript>", "", html, flags=re.DOTALL | re.IGNORECASE
            )
            html = re.sub(r"<svg[^>]*>.*?</svg>", "", html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r"<path[^>]*>", "", html, flags=re.IGNORECASE)
            html = re.sub(r"<g[^>]*>", "", html, flags=re.IGNORECASE)
            html = re.sub(r"<link[^>]*>", "", html, flags=re.IGNORECASE)
            html = re.sub(r"\s+", " ", html)
            return html.strip()

        def extract_buy_box_window(html: str, window_size_chars: int = 150000) -> str:
            """
            Extract focused HTML window around buy box markers using generic ecommerce patterns.

            Uses ranked anchor system: attribute anchors > button text anchors > variant gating anchors.
            All patterns are case-insensitive and work across unknown ecommerce sites.
            """
            cta_anchors = []
            variant_anchors = []

            atc_tokens = r"add[-_]to[-_](?:cart|bag|basket)|addtocart|addtobag|addtobasket|atc"
            purchase_tokens = (
                r"product[-_]form|productform|product__form|buy[-_]box|buybox|purchase|"
                r"product[-_]options|variants|variant|option|sticky[-_]atc"
            )

            strong_attr_patterns = [
                (
                    r'data-(?:testid|test|qa|cy)=["\'][^"\']*(?:'
                    + atc_tokens
                    + r"|"
                    + purchase_tokens
                    + r')[^"\']*["\']',
                    "strong_atc_testid",
                ),
                (
                    r'(?:id|class)=["\'][^"\']*(?:'
                    + atc_tokens
                    + r"|"
                    + purchase_tokens
                    + r')[^"\']*["\']',
                    "strong_atc_id_class",
                ),
            ]

            for pattern, name in strong_attr_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    cta_anchors.append((match.start(), name))

            button_text_patterns = [
                (
                    r'<(?:button|a\s+[^>]*role=["\']button["\']|[^>]*role=["\']button["\'])[^>]*>'
                    r'[^<]*(?:add\s+(?:to\s+)?(?:cart|bag|basket)|buy\s+now|checkout|purchase|reserve|preorder)'
                    r'[^<]*</(?:button|a)>',
                    "cta_button_text",
                ),
                (
                    r'<input[^>]*(?:type=["\'](?:submit|button)["\']|role=["\']button["\'])[^>]*'
                    r'(?:value=["\'][^"\']*(?:add\s+(?:to\s+)?(?:cart|bag|basket)|buy\s+now|checkout)'
                    r'[^"\']*["\']|>.*?(?:add\s+(?:to\s+)?(?:cart|bag|basket)|buy\s+now|checkout))',
                    "cta_input_button",
                ),
            ]

            for pattern, name in button_text_patterns:
                match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
                if match:
                    cta_anchors.append((match.start(), name))

            variant_gating_patterns = [
                (
                    r'>\s*(?:select|choose|pick)\s+(?:a\s+)?(?:size|option|colou?r)\s*<',
                    "variant_gating_text",
                ),
            ]

            for pattern, name in variant_gating_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    variant_anchors.append((match.start(), name))

            legacy_anchors = []
            atc_section_pos = html.find('id="add-to-cart-section"')
            if atc_section_pos >= 0:
                legacy_anchors.append((atc_section_pos, "legacy_add_to_cart_section"))
            variant_selection_pos = html.find('id="variant-selection"')
            if variant_selection_pos >= 0:
                legacy_anchors.append((variant_selection_pos, "legacy_variant_selection"))
            primary_button_pos = html.find('data-testid="primary-button"')
            if primary_button_pos >= 0:
                legacy_anchors.append((primary_button_pos, "legacy_primary_button"))
            size_selector_pos = html.find('data-testid="size-selector"')
            if size_selector_pos >= 0:
                legacy_anchors.append((size_selector_pos, "legacy_size_selector"))

            all_cta_anchors = sorted(cta_anchors + legacy_anchors, key=lambda x: x[0])
            all_variant_anchors = sorted(variant_anchors, key=lambda x: x[0])

            if all_cta_anchors and all_variant_anchors:
                cta_pos, cta_name = all_cta_anchors[0]
                variant_pos, variant_name = all_variant_anchors[0]

                start_pos = min(cta_pos, variant_pos)
                end_pos = max(cta_pos, variant_pos)

                span_size = end_pos - start_pos
                padding = max(50000, (window_size_chars - span_size) // 2)

                if span_size + (padding * 2) <= window_size_chars:
                    extracted_start = max(0, start_pos - padding)
                    extracted_end = min(len(html), end_pos + padding)
                    extracted = html[extracted_start:extracted_end]

                    logger.info(
                        "html_buy_box_extraction_dual_markers",
                        cta_anchor=cta_name,
                        variant_anchor=variant_name,
                        start_pos=extracted_start,
                        end_pos=extracted_end,
                        extracted_chars=len(extracted),
                        span_size=span_size,
                        padding=padding,
                        session_id=str(session_id),
                        page_type=page_type,
                    )
                    return extracted
                else:
                    half_window = window_size_chars // 2
                    cta_start = max(0, cta_pos - half_window)
                    cta_end = min(len(html), cta_pos + half_window)
                    variant_start = max(0, variant_pos - half_window)
                    variant_end = min(len(html), variant_pos + half_window)

                    cta_chunk = html[cta_start:cta_end]
                    variant_chunk = html[variant_start:variant_end]

                    extracted = (
                        cta_chunk + "\n\n[--- VARIANT SELECTION SECTION ---]\n\n" + variant_chunk
                    )

                    logger.info(
                        "html_buy_box_extraction_dual_window",
                        cta_anchor=cta_name,
                        variant_anchor=variant_name,
                        cta_chunk_size=len(cta_chunk),
                        variant_chunk_size=len(variant_chunk),
                        total_chars=len(extracted),
                        session_id=str(session_id),
                        page_type=page_type,
                    )
                    return extracted

            anchor_pos = None
            anchor_name = None

            if all_cta_anchors:
                anchor_pos, anchor_name = all_cta_anchors[0]
            elif all_variant_anchors:
                anchor_pos, anchor_name = all_variant_anchors[0]

            if anchor_pos is None:
                return html

            half_window = window_size_chars // 2
            start_pos = max(0, anchor_pos - half_window)
            end_pos = min(len(html), anchor_pos + half_window)

            extracted = html[start_pos:end_pos]

            logger.info(
                "html_buy_box_extraction_single_anchor",
                anchor_name=anchor_name,
                anchor_pos=anchor_pos,
                start_pos=start_pos,
                end_pos=end_pos,
                extracted_chars=len(extracted),
                session_id=str(session_id),
                page_type=page_type,
            )

            return extracted

        cleaned_html = strip_html_for_analysis(html)
        original_size = len(html)
        cleaned_size = len(cleaned_html)
        cleaned_bytes = len(cleaned_html.encode("utf-8"))

        atc_tokens = r"add[-_]to[-_](?:cart|bag|basket)|addtocart|addtobag|addtobasket|atc"
        purchase_tokens = (
            r"product[-_]form|productform|product__form|buy[-_]box|buybox|purchase|"
            r"product[-_]options|variants|variant|option|sticky[-_]atc"
        )

        critical_markers = {
            "id_add_to_cart_section": 'id="add-to-cart-section"' in cleaned_html,
            "data_testid_primary_button": 'data-testid="primary-button"' in cleaned_html,
            "id_variant_selection": 'id="variant-selection"' in cleaned_html,
            "data_testid_size_selector": 'data-testid="size-selector"' in cleaned_html,
            "any_atc_testid": bool(
                re.search(
                    r'data-(?:testid|test|qa|cy)=["\'][^"\']*(?:'
                    + atc_tokens
                    + r"|"
                    + purchase_tokens
                    + r')[^"\']*["\']',
                    cleaned_html,
                    re.IGNORECASE,
                )
            ),
            "any_atc_id_class": bool(
                re.search(
                    r'(?:id|class)=["\'][^"\']*(?:'
                    + atc_tokens
                    + r"|"
                    + purchase_tokens
                    + r')[^"\']*["\']',
                    cleaned_html,
                    re.IGNORECASE,
                )
            ),
            "any_atc_button_text": bool(
                re.search(
                    r'<(?:button|a\s+[^>]*role=["\']button["\']|[^>]*role=["\']button["\'])[^>]*>'
                    r'[^<]*(?:add\s+(?:to\s+)?(?:cart|bag|basket)|buy\s+now|checkout|purchase|reserve|preorder)'
                    r'[^<]*</(?:button|a)>',
                    cleaned_html,
                    re.IGNORECASE | re.DOTALL,
                )
            ),
            "any_buy_now_text": bool(
                re.search(
                    r'<(?:button|a\s+[^>]*role=["\']button["\'])[^>]*>[^<]*buy\s+now[^<]*</(?:button|a)>',
                    cleaned_html,
                    re.IGNORECASE | re.DOTALL,
                )
            ),
            "any_variant_gating_text": bool(
                re.search(
                    r'>\s*(?:select|choose|pick)\s+(?:a\s+)?(?:size|option|colou?r)\s*<',
                    cleaned_html,
                    re.IGNORECASE,
                )
            ),
            "add_to_cart_text": bool(
                re.search(r'>\s*add\s+to\s+cart\s*<', cleaned_html, re.IGNORECASE)
            ),
            "add_to_cart_dom_text": bool(
                re.search(r'>\s*add\s+to\s+cart\s*<', cleaned_html, re.IGNORECASE)
            ),
        }

        logger.info(
            "html_analysis_input_integrity",
            original_chars=original_size,
            original_bytes=len(html.encode("utf-8")),
            cleaned_chars=cleaned_size,
            cleaned_bytes=cleaned_bytes,
            markers_present=critical_markers,
            session_id=str(session_id),
            page_type=page_type,
            viewport=viewport,
        )

        use_buy_box_extraction = (
            os.getenv("HTML_ANALYSIS_BUY_BOX_EXTRACTION", "true").lower() == "true"
        )
        use_smart_chunking = os.getenv("HTML_ANALYSIS_SMART_CHUNKING", "true").lower() == "true"
        send_full_html = os.getenv("HTML_ANALYSIS_SEND_FULL_HTML", "false").lower() == "true"
        use_full_html_chunked = send_full_html and cleaned_size > max_html_chars

        if send_full_html and not use_full_html_chunked:
            if cleaned_size <= max_html_chars:
                html_to_send = cleaned_html
                chunking_mode = "full"
                logger.info(
                    "html_analysis_full_page_sent",
                    cleaned_chars=cleaned_size,
                    session_id=str(session_id),
                    page_type=page_type,
                )
            else:
                chunk_size = max_html_chars // 3
                head_chunk = cleaned_html[:chunk_size]
                mid_start = (len(cleaned_html) - chunk_size) // 2
                mid_chunk = cleaned_html[mid_start : mid_start + chunk_size]
                tail_chunk = cleaned_html[-chunk_size:]
                html_to_send = (
                    head_chunk
                    + "\n\n[--- HTML MIDDLE SECTION ---]\n\n"
                    + mid_chunk
                    + "\n\n[--- HTML TAIL ---]\n\n"
                    + tail_chunk
                )
                chunking_mode = "full_page_three_chunks"
                logger.info(
                    "html_analysis_full_page_three_chunks",
                    cleaned_size=cleaned_size,
                    head_size=len(head_chunk),
                    mid_size=len(mid_chunk),
                    tail_size=len(tail_chunk),
                    total_sent=len(html_to_send),
                    session_id=str(session_id),
                    page_type=page_type,
                )
        elif not use_full_html_chunked and use_buy_box_extraction and cleaned_size > max_html_chars:
            buy_box_html = extract_buy_box_window(cleaned_html, window_size_chars=max_html_chars)
            buy_box_extracted = len(buy_box_html) < len(cleaned_html)
            if len(buy_box_html) <= max_html_chars:
                html_to_send = buy_box_html
                chunking_mode = "buy_box_extraction"
                logger.info(
                    "html_analysis_buy_box_extraction_used",
                    extracted_chars=len(buy_box_html),
                    session_id=str(session_id),
                    page_type=page_type,
                )
            elif buy_box_extracted:
                html_to_send = buy_box_html[:max_html_chars]
                chunking_mode = "buy_box_extraction_truncated"
                logger.warning(
                    "html_analysis_buy_box_extraction_truncated",
                    extracted_chars=len(buy_box_html),
                    truncated_to=max_html_chars,
                    session_id=str(session_id),
                    page_type=page_type,
                )
            else:
                chunk_size = max_html_chars // 3
                head_chunk = cleaned_html[:chunk_size]
                mid_start = (len(cleaned_html) - chunk_size) // 2
                mid_chunk = cleaned_html[mid_start : mid_start + chunk_size]
                tail_chunk = cleaned_html[-chunk_size:]
                html_to_send = (
                    head_chunk
                    + "\n\n[--- HTML MIDDLE (no anchor found) ---]\n\n"
                    + mid_chunk
                    + "\n\n[--- HTML TAIL ---]\n\n"
                    + tail_chunk
                )
                chunking_mode = "head_mid_tail_fallback_no_anchor"
                logger.info(
                    "html_analysis_head_mid_tail_fallback_no_anchor",
                    original_size=original_size,
                    cleaned_size=cleaned_size,
                    head_size=len(head_chunk),
                    mid_size=len(mid_chunk),
                    tail_size=len(tail_chunk),
                    total_sent=len(html_to_send),
                    session_id=str(session_id),
                    page_type=page_type,
                )
        elif not use_full_html_chunked and cleaned_size <= max_html_chars:
            html_to_send = cleaned_html
            chunking_mode = "none"
        elif not use_full_html_chunked and use_smart_chunking and cleaned_size > max_html_chars:
            chunk_size = max_html_chars // 2
            head_chunk = cleaned_html[:chunk_size]
            tail_chunk = cleaned_html[-chunk_size:] if len(cleaned_html) > chunk_size else ""
            html_to_send = (
                head_chunk + "\n\n[HTML MIDDLE SECTION REMOVED FOR SIZE]\n\n" + tail_chunk
            )
            chunking_mode = "head_tail"
            logger.info(
                "html_analysis_smart_chunking",
                original_size=original_size,
                cleaned_size=cleaned_size,
                head_chunk_size=len(head_chunk),
                tail_chunk_size=len(tail_chunk),
                total_sent=len(html_to_send),
                session_id=str(session_id),
                page_type=page_type,
            )
        elif not use_full_html_chunked:
            html_to_send = cleaned_html[:max_html_chars]
            chunking_mode = "truncated"
            logger.info(
                "html_analysis_html_truncated",
                original_size=original_size,
                cleaned_size=cleaned_size,
                truncated_to=max_html_chars,
                session_id=str(session_id),
                page_type=page_type,
            )
        else:
            html_to_send = cleaned_html
            chunking_mode = "full_html_chunked"

        sent_chars = len(html_to_send)
        sent_bytes = len(html_to_send.encode("utf-8"))
        sent_markers = {
            "id_add_to_cart_section": 'id="add-to-cart-section"' in html_to_send,
            "data_testid_primary_button": 'data-testid="primary-button"' in html_to_send,
            "id_variant_selection": 'id="variant-selection"' in html_to_send,
            "data_testid_size_selector": 'data-testid="size-selector"' in html_to_send,
            "any_atc_testid": bool(
                re.search(
                    r'data-(?:testid|test|qa|cy)=["\'][^"\']*(?:'
                    + atc_tokens
                    + r"|"
                    + purchase_tokens
                    + r')[^"\']*["\']',
                    html_to_send,
                    re.IGNORECASE,
                )
            ),
            "any_atc_id_class": bool(
                re.search(
                    r'(?:id|class)=["\'][^"\']*(?:'
                    + atc_tokens
                    + r"|"
                    + purchase_tokens
                    + r')[^"\']*["\']',
                    html_to_send,
                    re.IGNORECASE,
                )
            ),
            "any_atc_button_text": bool(
                re.search(
                    r'<(?:button|a\s+[^>]*role=["\']button["\']|[^>]*role=["\']button["\'])[^>]*>'
                    r'[^<]*(?:add\s+(?:to\s+)?(?:cart|bag|basket)|buy\s+now|checkout|purchase|reserve|preorder)'
                    r'[^<]*</(?:button|a)>',
                    html_to_send,
                    re.IGNORECASE | re.DOTALL,
                )
            ),
            "any_buy_now_text": bool(
                re.search(
                    r'<(?:button|a\s+[^>]*role=["\']button["\'])[^>]*>[^<]*buy\s+now[^<]*</(?:button|a)>',
                    html_to_send,
                    re.IGNORECASE | re.DOTALL,
                )
            ),
            "any_variant_gating_text": bool(
                re.search(
                    r'>\s*(?:select|choose|pick)\s+(?:a\s+)?(?:size|option|colou?r)\s*<',
                    html_to_send,
                    re.IGNORECASE,
                )
            ),
            "add_to_cart_text": bool(
                re.search(r'>\s*add\s+to\s+cart\s*<', html_to_send, re.IGNORECASE)
            ),
            "add_to_cart_dom_text": bool(
                re.search(r'>\s*add\s+to\s+cart\s*<', html_to_send, re.IGNORECASE)
            ),
        }

        missing_markers = [
            k for k, v in critical_markers.items() if v and not sent_markers.get(k, False)
        ]

        if missing_markers:
            logger.warning(
                "html_analysis_markers_missing_attempting_recovery",
                missing_markers=missing_markers,
                chunking_mode=chunking_mode,
                session_id=str(session_id),
                page_type=page_type,
                viewport=viewport,
            )

            recovered_html = extract_buy_box_window(cleaned_html, window_size_chars=max_html_chars)
            if len(recovered_html) > max_html_chars:
                recovered_html = recovered_html[:max_html_chars]

            recovered_markers = {
                "id_add_to_cart_section": 'id="add-to-cart-section"' in recovered_html,
                "data_testid_primary_button": 'data-testid="primary-button"' in recovered_html,
                "id_variant_selection": 'id="variant-selection"' in recovered_html,
                "data_testid_size_selector": 'data-testid="size-selector"' in recovered_html,
                "any_atc_testid": bool(
                    re.search(
                        r'data-(?:testid|test|qa|cy)=["\'][^"\']*(?:'
                        + atc_tokens
                        + r"|"
                        + purchase_tokens
                        + r')[^"\']*["\']',
                        recovered_html,
                        re.IGNORECASE,
                    )
                ),
                "any_atc_id_class": bool(
                    re.search(
                        r'(?:id|class)=["\'][^"\']*(?:'
                        + atc_tokens
                        + r"|"
                        + purchase_tokens
                        + r')[^"\']*["\']',
                        recovered_html,
                        re.IGNORECASE,
                    )
                ),
                "any_atc_button_text": bool(
                    re.search(
                        r'<(?:button|a\s+[^>]*role=["\']button["\']|[^>]*role=["\']button["\'])[^>]*>'
                        r'[^<]*(?:add\s+(?:to\s+)?(?:cart|bag|basket)|buy\s+now|checkout|purchase|reserve|preorder)'
                        r'[^<]*</(?:button|a)>',
                        recovered_html,
                        re.IGNORECASE | re.DOTALL,
                    )
                ),
                "any_buy_now_text": bool(
                    re.search(
                        r'<(?:button|a\s+[^>]*role=["\']button["\'])[^>]*>[^<]*buy\s+now[^<]*</(?:button|a)>',
                        recovered_html,
                        re.IGNORECASE | re.DOTALL,
                    )
                ),
                "any_variant_gating_text": bool(
                    re.search(
                        r'>\s*(?:select|choose|pick)\s+(?:a\s+)?(?:size|option|colou?r)\s*<',
                        recovered_html,
                        re.IGNORECASE,
                    )
                ),
                "add_to_cart_text": bool(
                    re.search(r'>\s*add\s+to\s+cart\s*<', recovered_html, re.IGNORECASE)
                ),
                "add_to_cart_dom_text": bool(
                    re.search(r'>\s*add\s+to\s+cart\s*<', recovered_html, re.IGNORECASE)
                ),
            }

            still_missing = [
                k for k, v in critical_markers.items() if v and not recovered_markers.get(k, False)
            ]

            if len(still_missing) < len(missing_markers):
                html_to_send = recovered_html
                chunking_mode = "buy_box_extraction_recovery"
                sent_chars = len(html_to_send)
                sent_bytes = len(html_to_send.encode("utf-8"))
                sent_markers = recovered_markers
                missing_markers = still_missing

                logger.info(
                    "html_analysis_markers_recovery_successful",
                    recovered_markers=len(missing_markers) - len(still_missing),
                    still_missing=still_missing,
                    session_id=str(session_id),
                    page_type=page_type,
                    viewport=viewport,
                )
            else:
                logger.error(
                    "html_analysis_markers_recovery_failed",
                    missing_markers=missing_markers,
                    chunking_mode=chunking_mode,
                    session_id=str(session_id),
                    page_type=page_type,
                    viewport=viewport,
                )

        if missing_markers:
            logger.error(
                "html_analysis_markers_missing_in_sent_html",
                missing_markers=missing_markers,
                chunking_mode=chunking_mode,
                sent_chars=sent_chars,
                cleaned_chars=cleaned_size,
                session_id=str(session_id),
                page_type=page_type,
                viewport=viewport,
            )

        logger.info(
            "html_analysis_sent_html_integrity",
            sent_chars=sent_chars,
            sent_bytes=sent_bytes,
            markers_present=sent_markers,
            chunking_mode=chunking_mode,
            session_id=str(session_id),
            page_type=page_type,
            viewport=viewport,
        )

        if use_single_request and not use_full_html_chunked:
            logger.info(
                "html_analysis_single_request_mode",
                original_html_size=original_size,
                cleaned_html_size=cleaned_size,
                html_sent_size=len(html_to_send),
                chunking_mode=chunking_mode,
                reduction_percent=round(
                    100 * (1 - len(html_to_send) / original_size) if original_size > 0 else 0, 1
                ),
                session_id=str(session_id),
                page_type=page_type,
            )

            if page_type in ("cart", "checkout"):
                page_context = (
                    "PAGE CONTEXT: This HTML is from a CART or CHECKOUT page. "
                    "You MUST identify the main Checkout CTA (button or link: e.g. 'Proceed to checkout', 'Checkout', 'Go to checkout', 'Secure checkout') and return it in cart_confirmation.checkout. "
                    "form, add_to_cart, and variant_groups may be null/empty for cart pages; focus on cart_confirmation.view_cart and cart_confirmation.checkout.\n\n"
                )
                user_text = page_context + base_prompt + "\n\n" + "RAW HTML:\n" + html_to_send
            else:
                user_text = base_prompt + "\n\n" + "RAW HTML:\n" + html_to_send

            analysis_json, cost_data = _call_json_only(user_text)
            if not isinstance(analysis_json, dict):
                logger.error("html_analysis_single_request_failed")
                return None

            if cost_data:
                print("\n   💰 HTML Analysis Cost Summary:")
                print("      API calls: 1")
                print(f"      Input tokens: {cost_data['input_tokens']:,}")
                print(f"      Output tokens: {cost_data['output_tokens']:,}")
                print(f"      Total tokens: {cost_data['total_tokens']:,}")
                print(f"      Estimated cost: ${cost_data['estimated_cost_usd']:.6f}")
                analysis_json["_cost_metadata"] = {
                    "input_tokens": cost_data["input_tokens"],
                    "output_tokens": cost_data["output_tokens"],
                    "total_tokens": cost_data["total_tokens"],
                    "estimated_cost_usd": cost_data["estimated_cost_usd"],
                    "chunk_calls": 0,
                    "consolidation_calls": 1,
                    "mode": "single_request",
                }

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

            log_details = {
                "mode": "automatic_single_request",
                "size_bytes": size,
                "checksum": checksum,
                "storage_uri": storage_uri,
                "has_variants": analysis_json.get("has_variants", False),
                "form_found": analysis_json.get("form", {}).get("found", False),
            }
            if cost_data:
                log_details.update(
                    {
                        "cost_metadata": analysis_json.get("_cost_metadata", {}),
                        "estimated_cost_usd": cost_data["estimated_cost_usd"],
                        "total_api_calls": 1,
                    }
                )

            repository.create_log(
                session_id=session_id,
                level="info",
                event_type="html_analysis",
                message="HTML analysis completed (automatic mode, single request)",
                details=log_details,
            )

            logger.info(
                "html_analysis_completed_automatic_single",
                session_id=str(session_id),
                page_id=str(page_id),
                size_bytes=size,
                checksum=checksum,
                storage_uri=storage_uri,
            )

            analysis_json["_file_path"] = str(analysis_path.absolute())
            return analysis_json

        if use_full_html_chunked:
            chunk_chars = int(os.getenv("HTML_ANALYSIS_FULL_HTML_CHUNK_CHARS", "100000"))
            max_chunks = int(os.getenv("HTML_ANALYSIS_FULL_HTML_MAX_CHUNKS", "60"))
            strategy = "all"
            logger.info(
                "html_analysis_full_html_chunked_mode",
                cleaned_size=cleaned_size,
                chunk_chars=chunk_chars,
                max_chunks=max_chunks,
                session_id=str(session_id),
                page_type=page_type,
            )
        else:
            chunk_chars = int(os.getenv("HTML_ANALYSIS_CHUNK_CHARS", "80000"))
            max_chunks = int(os.getenv("HTML_ANALYSIS_MAX_CHUNKS", "25"))
            strategy = os.getenv("HTML_ANALYSIS_CHUNK_STRATEGY", "all")

        chunks = _chunk_text(cleaned_html, chunk_chars)
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
            full_html_chunked=use_full_html_chunked,
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

        input_per_1m = float(os.getenv("OPENAI_PRICE_INPUT_PER_1M", "0"))
        output_per_1m = float(os.getenv("OPENAI_PRICE_OUTPUT_PER_1M", "0"))
        total_cost_data = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "chunk_calls": 0,
            "consolidation_calls": 0,
        }

        chunk_page_context = ""
        if page_type in ("cart", "checkout"):
            chunk_page_context = (
                "PAGE CONTEXT: This HTML is from a CART or CHECKOUT page. "
                "Identify the main Checkout CTA and return it in cart_confirmation.checkout when found.\n\n"
            )
        partials: list[dict] = []
        for idx, ch in enumerate(selected, start=1):
            user_text = (
                chunk_page_context
                + base_prompt
                + "\n\n"
                + "IMPORTANT: You are receiving only a PARTIAL CHUNK of the full HTML.\n"
                + "Extract whatever you can FROM THIS CHUNK ONLY. If unknown, leave null/empty.\n"
                + f"CHUNK {idx} of {len(selected)}\n"
                + "RAW HTML CHUNK:\n"
                + ch
            )
            part, cost_data = _call_json_only(user_text)
            if isinstance(part, dict):
                part["_chunk_index"] = idx
                part["_chunk_total"] = len(selected)
                partials.append(part)
            if cost_data:
                total_cost_data["input_tokens"] += cost_data["input_tokens"]
                total_cost_data["output_tokens"] += cost_data["output_tokens"]
                total_cost_data["total_tokens"] += cost_data["total_tokens"]
                total_cost_data["estimated_cost_usd"] += cost_data["estimated_cost_usd"]
                total_cost_data["chunk_calls"] += 1

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

        analysis_json, consolidation_cost = _call_json_only(consolidate_text)
        if not isinstance(analysis_json, dict):
            logger.error("html_analysis_consolidation_failed")
            return None

        if consolidation_cost:
            total_cost_data["input_tokens"] += consolidation_cost["input_tokens"]
            total_cost_data["output_tokens"] += consolidation_cost["output_tokens"]
            total_cost_data["total_tokens"] += consolidation_cost["total_tokens"]
            total_cost_data["estimated_cost_usd"] += consolidation_cost["estimated_cost_usd"]
            total_cost_data["consolidation_calls"] = 1

        if input_per_1m > 0 or output_per_1m > 0:
            print("\n   💰 HTML Analysis Cost Summary:")
            print(f"      Chunk calls: {total_cost_data['chunk_calls']}")
            print(f"      Consolidation calls: {total_cost_data['consolidation_calls']}")
            total_calls = total_cost_data["chunk_calls"] + total_cost_data["consolidation_calls"]
            print(f"      Total API calls: {total_calls}")
            print(f"      Input tokens: {total_cost_data['input_tokens']:,}")
            print(f"      Output tokens: {total_cost_data['output_tokens']:,}")
            print(f"      Total tokens: {total_cost_data['total_tokens']:,}")
            print(f"      Estimated cost: ${total_cost_data['estimated_cost_usd']:.6f}")
            analysis_json["_cost_metadata"] = total_cost_data

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

        log_details = {
            "mode": "automatic",
            "size_bytes": size,
            "checksum": checksum,
            "storage_uri": storage_uri,
            "has_variants": analysis_json.get("has_variants", False),
            "form_found": analysis_json.get("form", {}).get("found", False),
        }
        if input_per_1m > 0 or output_per_1m > 0:
            log_details.update(
                {
                    "cost_metadata": total_cost_data,
                    "estimated_cost_usd": total_cost_data["estimated_cost_usd"],
                    "total_api_calls": total_cost_data["chunk_calls"]
                    + total_cost_data["consolidation_calls"],
                }
            )

        repository.create_log(
            session_id=session_id,
            level="info",
            event_type="html_analysis",
            message="HTML analysis completed (automatic mode)",
            details=log_details,
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
