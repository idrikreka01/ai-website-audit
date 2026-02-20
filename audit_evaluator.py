"""
Production-ready pipeline for evaluating audit questions using OpenAI Responses API.

This module implements a single-request evaluation system that processes HTML chunks,
screenshots, and questions to produce structured audit results.
"""

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from openai import OpenAI

from shared.config import get_config


class PolicyLinkMatcher:
    """Helper functions for semantic policy link matching."""

    @staticmethod
    def has_return_policy_link(text_or_links: str) -> bool:
        """
        Check if text contains return policy link indicators.

        Args:
            text_or_links: Text content or link labels/hrefs

        Returns:
            True if any return policy indicators found
        """
        if not text_or_links:
            return False

        text_lower = text_or_links.lower()
        patterns = [
            "return",
            "returns",
            "return policy",
            "refund policy",
            "returns & exchanges",
            "exchange policy",
        ]
        return any(pattern in text_lower for pattern in patterns)

    @staticmethod
    def has_privacy_policy_link(text_or_links: str) -> bool:
        """
        Check if text contains privacy policy link indicators.

        Args:
            text_or_links: Text content or link labels/hrefs

        Returns:
            True if privacy policy indicator found
        """
        if not text_or_links:
            return False

        return "privacy policy" in text_or_links.lower()

    @staticmethod
    def has_terms_link(text_or_links: str) -> bool:
        """
        Check if text contains terms link indicators.

        Args:
            text_or_links: Text content or link labels/hrefs

        Returns:
            True if any terms indicators found
        """
        if not text_or_links:
            return False

        text_lower = text_or_links.lower()
        patterns = ["terms", "terms of service", "terms & conditions", "terms and conditions"]
        return any(pattern in text_lower for pattern in patterns)


class HTMLPreprocessor:
    """Preprocesses HTML by stripping unnecessary content and chunking."""

    @staticmethod
    def strip_html(html: str) -> str:
        """
        Strip scripts, styles, and comments from HTML.

        Args:
            html: Raw HTML content

        Returns:
            Cleaned HTML string
        """
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

        html = re.sub(r"<noscript[^>]*>.*?</noscript>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<svg[^>]*>.*?</svg>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<path[^>]*>", "", html, flags=re.IGNORECASE)
        html = re.sub(r"<g[^>]*>", "", html, flags=re.IGNORECASE)

        html = re.sub(r"<link[^>]*>", "", html, flags=re.IGNORECASE)

        html = re.sub(r"\s+", " ", html)
        cleaned = html.strip()
        return cleaned

    @staticmethod
    def chunk_html(html: str, max_chars: int = 8000) -> List[str]:
        """
        Chunk HTML into segments of max_chars length, preserving structure.

        Args:
            html: HTML content to chunk
            max_chars: Maximum characters per chunk

        Returns:
            List of HTML chunks
        """
        cleaned = HTMLPreprocessor.strip_html(html)

        if len(cleaned) <= max_chars:
            return [cleaned]

        chunks = []
        current_chunk = ""

        for char in cleaned:
            if len(current_chunk) + len(char) > max_chars and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = char
            else:
                current_chunk += char

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks


class QuestionSorter:
    """Sorts questions by tier (ASC) and severity (DESC)."""

    @staticmethod
    def sort_questions(questions: Dict[str, Dict[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Sort questions by tier ascending, then severity descending.

        Args:
            questions: Dict mapping question_id to question data

        Returns:
            List of (question_id, question_data) tuples sorted correctly
        """
        from sqlalchemy import select

        from shared.db import get_audit_questions_table, get_db_session

        with get_db_session() as session:
            questions_table = get_audit_questions_table()

            question_ids = [int(qid) for qid in questions.keys()]
            stmt = select(questions_table).where(questions_table.c.question_id.in_(question_ids))
            results = session.execute(stmt).all()

            question_metadata = {
                str(row.question_id): {"tier": row.tier, "severity": row.severity}
                for row in results
            }
        sorted_items = sorted(
            questions.items(),
            key=lambda x: (
                question_metadata.get(x[0], {}).get("tier", 999),
                -question_metadata.get(x[0], {}).get("severity", 0),
            ),
        )

        return sorted_items


class AuditRequestBuilder:
    """Builds OpenAI Responses API request with mixed content types."""

    def __init__(self, artifacts_dir: str = "./artifacts"):
        """
        Initialize the request builder.

        Args:
            artifacts_dir: Base directory for artifacts
        """
        self.artifacts_dir = Path(artifacts_dir)

    def _load_performance_data(
        self, session_id: str, page_type: str, repository
    ) -> Optional[Dict[str, Any]]:
        """
        Load performance data (load_timings) from audit_pages table.

        Returns performance data for desktop and mobile viewports, or None if not available.
        """
        if not repository:
            return None

        try:
            from uuid import UUID

            session_uuid = (
                UUID(session_id.split("__")[-1]) if "__" in session_id else UUID(session_id)
            )
            pages = repository.get_pages_by_session_id(session_uuid)

            performance_data = {}

            for page in pages:
                if page.get("page_type") == page_type:
                    viewport = page.get("viewport")
                    load_timings = page.get("load_timings", {})

                    if load_timings and isinstance(load_timings, dict):
                        if viewport not in performance_data:
                            performance_data[viewport] = {}

                        total_load_ms = load_timings.get("total_load_duration_ms")
                        if total_load_ms is not None:
                            performance_data[viewport]["total_load_duration_ms"] = total_load_ms

                        network_idle_ms = load_timings.get("network_idle_duration_ms")
                        if network_idle_ms is not None:
                            performance_data[viewport]["network_idle_duration_ms"] = network_idle_ms

                        ready_time = load_timings.get("ready")
                        if ready_time:
                            performance_data[viewport]["ready_time"] = ready_time

                        soft_timeout = load_timings.get("soft_timeout")
                        if soft_timeout is not None:
                            performance_data[viewport]["soft_timeout"] = soft_timeout

            return performance_data if performance_data else None

        except Exception:
            return None

    def load_screenshot_url(self, session_id: str, page_type: str, viewport: str) -> Optional[str]:
        """
        Load screenshot URL from a URL file if it exists.

        Args:
            session_id: Session identifier (format: domain__uuid)
            page_type: Page type (homepage, product, etc.)
            viewport: Viewport (desktop, mobile)

        Returns:
            URL string if file exists, None otherwise
        """
        artifact_page_type = "pdp" if page_type == "product" else page_type
        url_file_path = (
            self.artifacts_dir / session_id / artifact_page_type / viewport / "screenshot_url.txt"
        )

        if url_file_path.exists():
            with open(url_file_path, "r", encoding="utf-8") as f:
                url = f.read().strip()
                if url:
                    return url

        return None

    def load_artifact(
        self,
        session_id: str,
        page_type: str,
        viewport: str,
        artifact_type: str,
        include_screenshots: bool = False,
    ) -> Optional[str]:
        """
        Load an artifact file.

        Args:
            session_id: Session identifier (format: domain__uuid)
            page_type: Page type (homepage, product, etc.)
            viewport: Viewport (desktop, mobile)
            artifact_type: Type of artifact (html_gz, visible_text, features_json, screenshot)
            include_screenshots: If False, screenshots return None (to avoid base64 in request)

        Returns:
            Content as string, or None if not found
        """
        if artifact_type == "screenshot" and not include_screenshots:
            return None

        artifact_page_type = "pdp" if page_type == "product" else page_type

        ext_map = {
            "html_gz": "html.gz",
            "visible_text": "txt",
            "features_json": "json",
            "screenshot": "png",
        }
        ext = ext_map.get(artifact_type, "")
        filename = (
            f"{artifact_type}.{ext}" if artifact_type != "screenshot" else f"screenshot.{ext}"
        )

        artifact_path = self.artifacts_dir / session_id / artifact_page_type / viewport / filename

        if not artifact_path.exists():
            return None

        if artifact_type == "html_gz":
            import gzip

            with gzip.open(artifact_path, "rt", encoding="utf-8") as f:
                content = f.read()
                return content
        elif artifact_type == "screenshot":
            with open(artifact_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
                mime_type = "image/png"
                return f"data:{mime_type};base64,{image_data}"
        else:
            with open(artifact_path, "r", encoding="utf-8") as f:
                content = f.read()
                return content

    def build_request(
        self,
        session_id: str,
        page_type: str,
        questions: Dict[str, Dict[str, Any]],
        chunk_size: int = 8000,
        include_screenshots: bool = False,
        repository=None,
    ) -> Dict[str, Any]:
        """
        Build OpenAI Responses API request with all context and questions.

        Args:
            session_id: Session identifier
            page_type: Page type (homepage, product, cart, checkout)
            questions: Questions dict from get_questions_by_page_type
            chunk_size: Maximum characters per HTML chunk
            include_screenshots: If True, include base64 screenshots (default False)

        Returns:
            Request payload for OpenAI Responses API
        """
        content_items = []

        system_instruction = (
            "You are an expert e-commerce website auditor. "
            "Evaluate each question against the evidence (HTML, screenshots, text, features).\n\n"
            "STRICT EVALUATION RULES:\n"
            "1. Return exactly ONE result per question_id. No missing IDs, no duplicates.\n"
            "2. Allowed outputs: PASS, FAIL, or UNKNOWN.\n"
            "3. Confidence gating: FAIL requires confidence >= 8 AND clear evidence. "
            "If evidence missing/unclear or confidence < 8, return UNKNOWN.\n"
            "4. Device rule: If mobile fails, overall is FAIL (both must pass).\n"
            "5. Evidence-based only. Use only the provided evidence blocks.\n"
            "6. Answer: Reasoning only. No chunk refs or technical citations. Plain language.\n"
            "7. Evidence field: Cite labels (e.g. DESKTOP_HTML_CHUNK 01, MOBILE_VISIBLE_TEXT) "
            "ONLY in evidence field, not in answer.\n"
            "8. Semantic equivalence for policy labels. Do not fail on wording when same.\n\n"
            "EVALUATION PROCESS:\n"
            "1. Review PASS/FAIL/UNKNOWN criteria.\n"
            "2. Examine ALL evidence (HTML, text, features JSON, screenshots, performance).\n"
            "3. Check desktop AND mobile.\n"
            "4. Criteria met on BOTH devices?\n"
            "5. PASS only if clearly met on both.\n"
            "6. FAIL only if clearly NOT met AND confidence >= 8 AND clear evidence.\n"
            "7. UNKNOWN if insufficient/unclear/conflicting or confidence < 8.\n"
            "8. Clear answer in plain language, no chunk refs.\n"
            "9. Evidence field: cite source labels.\n"
            "10. confidence_score_1_to_10. If < 8 return UNKNOWN. "
            "FAIL only when >= 8 and evidence clear.\n"
            "   - 10 = Very clear. 7-9 = Mostly clear. 4-6 = Prefer UNKNOWN. 1-3 = UNKNOWN.\n\n"
            'Return results as JSON: {"results": [{"question_id": "string", '
            '"pass_fail": "PASS|FAIL|UNKNOWN", "answer": "string", '
            '"evidence": "string", "confidence_score_1_to_10": 1-10}]}'
        )

        content_items.append({"type": "input_text", "text": system_instruction})

        desktop_html = self.load_artifact(session_id, page_type, "desktop", "html_gz")
        if desktop_html:
            chunks = HTMLPreprocessor.chunk_html(desktop_html, chunk_size)

            max_chunks = 5
            if len(chunks) > max_chunks:
                chunks = chunks[:max_chunks]

            for idx, chunk in enumerate(chunks, 1):
                labeled_chunk = f"[DESKTOP_HTML_CHUNK {idx:02d}]\n{chunk}\n[/DESKTOP_HTML_CHUNK]"
                content_items.append({"type": "input_text", "text": labeled_chunk})

        mobile_html = self.load_artifact(session_id, page_type, "mobile", "html_gz")
        if mobile_html:
            chunks = HTMLPreprocessor.chunk_html(mobile_html, chunk_size)

            max_chunks = 5
            if len(chunks) > max_chunks:
                chunks = chunks[:max_chunks]

            for idx, chunk in enumerate(chunks, 1):
                labeled_chunk = f"[MOBILE_HTML_CHUNK {idx:02d}]\n{chunk}\n[/MOBILE_HTML_CHUNK]"
                content_items.append({"type": "input_text", "text": labeled_chunk})

        desktop_visible_text = self.load_artifact(session_id, page_type, "desktop", "visible_text")
        if desktop_visible_text:
            txt = f"[DESKTOP_VISIBLE_TEXT]\n{desktop_visible_text}\n[/DESKTOP_VISIBLE_TEXT]"
            content_items.append({"type": "input_text", "text": txt})

        mobile_visible_text = self.load_artifact(session_id, page_type, "mobile", "visible_text")
        if mobile_visible_text:
            txt = f"[MOBILE_VISIBLE_TEXT]\n{mobile_visible_text}\n[/MOBILE_VISIBLE_TEXT]"
            content_items.append({"type": "input_text", "text": txt})

        desktop_features_json = self.load_artifact(
            session_id, page_type, "desktop", "features_json"
        )
        if desktop_features_json:
            txt = f"[DESKTOP_FEATURES_JSON]\n{desktop_features_json}\n[/DESKTOP_FEATURES_JSON]"
            content_items.append({"type": "input_text", "text": txt})

        mobile_features_json = self.load_artifact(session_id, page_type, "mobile", "features_json")
        if mobile_features_json:
            txt = f"[MOBILE_FEATURES_JSON]\n{mobile_features_json}\n[/MOBILE_FEATURES_JSON]"
            content_items.append({"type": "input_text", "text": txt})

        desktop_screenshot_url = self.load_screenshot_url(session_id, page_type, "desktop")
        if desktop_screenshot_url:
            content_items.append({"type": "input_image", "image_url": desktop_screenshot_url})

        mobile_screenshot_url = self.load_screenshot_url(session_id, page_type, "mobile")
        if mobile_screenshot_url:
            content_items.append({"type": "input_image", "image_url": mobile_screenshot_url})

        performance_data = self._load_performance_data(session_id, page_type, repository)
        if performance_data:
            perf_text = "[PERFORMANCE_DATA]\n"
            perf_text += json.dumps(performance_data, indent=2)
            perf_text += "\n[/PERFORMANCE_DATA]"
            content_items.append({"type": "input_text", "text": perf_text})

        sorted_questions = QuestionSorter.sort_questions(questions)

        questions_block = "[QUESTIONS]\n\n"
        for question_id, question_data in sorted_questions:
            ai_criteria = question_data.get("ai", "")
            questions_block += f"Question ID: {question_id}\n{ai_criteria}\n\n{'=' * 80}\n\n"

        questions_block += "[/QUESTIONS]"

        content_items.append({"type": "input_text", "text": questions_block})

        input_content = [{"role": "user", "content": content_items}]

        return {
            "input": input_content,
            "model": "gpt-5.2",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "audit_results",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "results": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "question_id": {"type": "string"},
                                        "pass_fail": {
                                            "type": "string",
                                            "enum": ["PASS", "FAIL", "UNKNOWN"],
                                        },
                                        "answer": {"type": "string"},
                                        "evidence": {"type": "string"},
                                        "confidence_score_1_to_10": {
                                            "type": "integer",
                                            "minimum": 1,
                                            "maximum": 10,
                                        },
                                    },
                                    "required": [
                                        "question_id",
                                        "pass_fail",
                                        "answer",
                                        "evidence",
                                        "confidence_score_1_to_10",
                                    ],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["results"],
                        "additionalProperties": False,
                    },
                }
            },
        }


class AuditEvaluator:
    """Main evaluator that orchestrates the audit process."""

    @staticmethod
    def calculate_cost_usd(
        response, input_per_1m: float, output_per_1m: float
    ) -> Optional[Dict[str, Any]]:
        """
        Calculate estimated API cost from response usage.

        Args:
            response: OpenAI API response object
            input_per_1m: Price per 1M input tokens
            output_per_1m: Price per 1M output tokens

        Returns:
            Dict with token counts and estimated cost, or None if usage unavailable
        """
        if not hasattr(response, "usage") or not response.usage:
            return None

        usage = response.usage
        input_tokens = (
            getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None) or 0
        )
        output_tokens = (
            getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", None) or 0
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

    def __init__(self, artifacts_dir: str = "./artifacts"):
        """
        Initialize the evaluator.

        Args:
            artifacts_dir: Base directory for artifacts
        """
        self.artifacts_dir = artifacts_dir
        self.builder = AuditRequestBuilder(artifacts_dir)

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            try:
                config = get_config()
                api_key = config.openai_api_key
            except Exception:
                pass

        self.client = OpenAI(api_key=api_key) if api_key else None

    def run_audit(
        self,
        session_id: str,
        page_type: str,
        questions: Dict[str, Dict[str, Any]],
        chunk_size: int = 8000,
        model: str = "gpt-5.2",
        save_response: bool = True,
        include_screenshots: bool = False,
        repository=None,
    ) -> Dict[str, Any]:
        """
        Run audit evaluation for given questions.

        Args:
            session_id: Session identifier
            page_type: Page type (homepage, product, cart, checkout)
            questions: Questions dict from get_questions_by_page_type
            chunk_size: Maximum characters per HTML chunk
            model: OpenAI model to use
            save_response: Whether to save response to answers.json file
            include_screenshots: If True, include base64 screenshots (default False)
            repository: Optional AuditRepository instance to save results to database

        Returns:
            Dict mapping question id to result, reason, confidence_score (e.g. PASS|FAIL|UNKNOWN).

        Raises:
            ValueError: If OpenAI API key is not configured
            RuntimeError: If API call fails or response is invalid
        """
        if not self.client:
            raise ValueError(
                "OpenAI API key not configured. Set OPENAI_API_KEY environment variable."
            )

        input_per_1m = float(os.getenv("OPENAI_PRICE_INPUT_PER_1M", "0"))
        output_per_1m = float(os.getenv("OPENAI_PRICE_OUTPUT_PER_1M", "0"))

        max_questions_per_batch = 30
        question_items = list(questions.items())
        total_questions = len(question_items)

        if total_questions <= max_questions_per_batch:
            return self._run_single_batch(
                session_id,
                page_type,
                questions,
                chunk_size,
                model,
                save_response,
                include_screenshots,
                repository,
                input_per_1m,
                output_per_1m,
            )

        all_results = {}
        num_batches = (total_questions + max_questions_per_batch - 1) // max_questions_per_batch

        for batch_idx in range(num_batches):
            start_idx = batch_idx * max_questions_per_batch
            end_idx = min(start_idx + max_questions_per_batch, total_questions)
            batch_questions = dict(question_items[start_idx:end_idx])

            batch_results = self._run_single_batch(
                session_id,
                page_type,
                batch_questions,
                chunk_size,
                model,
                False,
                include_screenshots,
                repository,
                input_per_1m,
                output_per_1m,
            )
            all_results.update(batch_results)

        if save_response:
            from pathlib import Path

            artifact_page_type = "pdp" if page_type == "product" else page_type
            output_dir = Path(self.artifacts_dir) / session_id / artifact_page_type
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / "answers.json"

            output_data = {
                "metadata": {
                    "model": model,
                    "session_id": session_id,
                    "page_type": page_type,
                    "batched": True,
                    "num_batches": num_batches,
                },
                "results": all_results,
            }

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

        if repository:
            saved_count = 0
            for question_id_str, result_data in all_results.items():
                try:
                    question_id = int(question_id_str)
                    result_value = result_data.get("result", "fail")
                    reason = result_data.get("reason", "")
                    confidence_score = result_data.get("confidence_score", 5)

                    repository.create_audit_result(
                        question_id=question_id,
                        session_id=session_id,
                        result=result_value,
                        reason=reason,
                        confidence_score=confidence_score,
                    )
                    saved_count += 1
                except (ValueError, TypeError):
                    pass
                except Exception:
                    pass

        return all_results

    def _run_single_batch(
        self,
        session_id: str,
        page_type: str,
        questions: Dict[str, Dict[str, Any]],
        chunk_size: int,
        model: str,
        save_response: bool,
        include_screenshots: bool,
        repository,
        input_per_1m: float,
        output_per_1m: float,
    ) -> Dict[str, Any]:
        """Run a single batch of questions."""
        request_payload = self.builder.build_request(
            session_id,
            page_type,
            questions,
            chunk_size,
            include_screenshots=include_screenshots,
            repository=repository,
        )
        request_payload["model"] = model

        try:
            response = self.client.responses.create(**request_payload)

            cost_data = self.calculate_cost_usd(response, input_per_1m, output_per_1m)

            result_text = None

            if hasattr(response, "output_text") and response.output_text:
                result_text = response.output_text
            elif hasattr(response, "output") and response.output:
                if isinstance(response.output, str):
                    result_text = response.output
                elif isinstance(response.output, list):
                    text_parts = []
                    for idx, item in enumerate(response.output):
                        if isinstance(item, dict):
                            if item.get("type") == "output_text":
                                text_parts.append(item.get("text", ""))
                            elif item.get("type") == "message":
                                content = item.get("content", [])
                                if isinstance(content, list):
                                    for content_item in content:
                                        if (
                                            isinstance(content_item, dict)
                                            and content_item.get("type") == "text"
                                        ):
                                            text_parts.append(content_item.get("text", ""))
                                elif isinstance(content, str):
                                    text_parts.append(content)
                            elif "text" in item:
                                text_parts.append(item.get("text", ""))

                    if text_parts:
                        result_text = "".join(text_parts)

            if not result_text:
                raise RuntimeError(
                    "Empty content in response - no output_text or extractable text found"
                )

            try:
                result_json = json.loads(result_text)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON in response: {e}")

            if "results" not in result_json:
                raise RuntimeError("Response missing 'results' field")

            results_list = result_json.get("results", [])

            expected_question_ids = set(str(qid) for qid in questions.keys())
            received_question_ids = set(str(item.get("question_id", "")) for item in results_list)

            missing_ids = expected_question_ids - received_question_ids
            extra_ids = received_question_ids - expected_question_ids
            duplicates = [
                qid
                for qid in received_question_ids
                if sum(1 for item in results_list if str(item.get("question_id", "")) == qid) > 1
            ]

            if missing_ids:
                raise RuntimeError(f"Missing question IDs in response: {sorted(missing_ids)}")
            if extra_ids:
                raise RuntimeError(f"Extra question IDs in response: {sorted(extra_ids)}")
            if duplicates:
                raise RuntimeError(f"Duplicate question IDs in response: {sorted(duplicates)}")

            transformed = self._transform_response(result_json, questions, session_id, page_type)

            if save_response:
                from pathlib import Path

                artifact_page_type = "pdp" if page_type == "product" else page_type
                output_dir = Path(self.artifacts_dir) / session_id / artifact_page_type
                output_dir.mkdir(parents=True, exist_ok=True)
                output_file = output_dir / "answers.json"

                output_data = {
                    "metadata": {"model": model, "session_id": session_id, "page_type": page_type},
                    "results": transformed,
                }

                if cost_data:
                    output_data["metadata"].update(
                        {
                            "input_tokens": cost_data["input_tokens"],
                            "output_tokens": cost_data["output_tokens"],
                            "total_tokens": cost_data["total_tokens"],
                            "estimated_cost_usd": cost_data["estimated_cost_usd"],
                        }
                    )

                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(output_data, f, indent=2, ensure_ascii=False)

            if repository:
                saved_count = 0
                for question_id_str, result_data in transformed.items():
                    try:
                        question_id = int(question_id_str)
                        result_value = result_data.get("result", "fail")
                        reason = result_data.get("reason", "")
                        confidence_score = result_data.get("confidence_score", 5)

                        repository.create_audit_result(
                            question_id=question_id,
                            session_id=session_id,
                            result=result_value,
                            reason=reason,
                            confidence_score=confidence_score,
                        )
                        saved_count += 1
                    except (ValueError, TypeError):
                        pass
                    except Exception:
                        pass

            return transformed

        except Exception as e:
            error_str = str(e).lower()
            if (
                "json_schema" in error_str
                or "text.format" in error_str
                or "structured_outputs" in error_str
                or "name" in error_str
            ):
                request_payload.pop("text", None)
                request_payload["text"] = {"format": {"type": "json_object"}}

                request_payload_fallback = self.builder.build_request(
                    session_id,
                    page_type,
                    questions,
                    chunk_size,
                    include_screenshots=include_screenshots,
                    repository=repository,
                )
                request_payload_fallback["model"] = model
                request_payload_fallback.pop("text", None)
                request_payload_fallback["text"] = {"format": {"type": "json_object"}}
                response = self.client.responses.create(**request_payload_fallback)

                cost_data = self.calculate_cost_usd(response, input_per_1m, output_per_1m)

                result_text = None

                if hasattr(response, "output_text") and response.output_text:
                    result_text = response.output_text
                elif hasattr(response, "output") and response.output:
                    if isinstance(response.output, str):
                        result_text = response.output
                    elif isinstance(response.output, list):
                        text_parts = []
                        for idx, item in enumerate(response.output):
                            if isinstance(item, dict):
                                if item.get("type") == "output_text":
                                    text_parts.append(item.get("text", ""))
                                elif item.get("type") == "message":
                                    content = item.get("content", [])
                                    if isinstance(content, list):
                                        for content_item in content:
                                            if (
                                                isinstance(content_item, dict)
                                                and content_item.get("type") == "text"
                                            ):
                                                text_parts.append(content_item.get("text", ""))
                                    elif isinstance(content, str):
                                        text_parts.append(content)
                                elif "text" in item:
                                    text_parts.append(item.get("text", ""))

                        if text_parts:
                            result_text = "".join(text_parts)

                if not result_text:
                    raise RuntimeError("Empty content in response after fallback")

                result_json = json.loads(result_text)

                if "results" not in result_json:
                    raise RuntimeError("Response missing 'results' field after fallback")

                results_list = result_json.get("results", [])
                expected_question_ids = set(str(qid) for qid in questions.keys())
                received_question_ids = set(
                    str(item.get("question_id", "")) for item in results_list
                )

                missing_ids = expected_question_ids - received_question_ids
                extra_ids = received_question_ids - expected_question_ids
                duplicates = [
                    qid
                    for qid in received_question_ids
                    if sum(1 for item in results_list if str(item.get("question_id", "")) == qid)
                    > 1
                ]

                if missing_ids:
                    raise RuntimeError(
                        f"Missing question IDs in fallback response: {sorted(missing_ids)}"
                    )
                if extra_ids:
                    raise RuntimeError(
                        f"Extra question IDs in fallback response: {sorted(extra_ids)}"
                    )
                if duplicates:
                    raise RuntimeError(
                        f"Duplicate question IDs in fallback response: {sorted(duplicates)}"
                    )

                transformed = self._transform_response(
                    result_json, questions, session_id, page_type
                )

                if save_response:
                    from pathlib import Path

                    artifact_page_type = "pdp" if page_type == "product" else page_type
                    output_dir = Path(self.artifacts_dir) / session_id / artifact_page_type
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_file = output_dir / "answers.json"

                    output_data = {
                        "metadata": {
                            "model": model,
                            "session_id": session_id,
                            "page_type": page_type,
                        },
                        "results": transformed,
                    }

                    if cost_data:
                        output_data["metadata"].update(
                            {
                                "input_tokens": cost_data["input_tokens"],
                                "output_tokens": cost_data["output_tokens"],
                                "total_tokens": cost_data["total_tokens"],
                                "estimated_cost_usd": cost_data["estimated_cost_usd"],
                            }
                        )

                    with open(output_file, "w", encoding="utf-8") as f:
                        json.dump(output_data, f, indent=2, ensure_ascii=False)

                if repository:
                    saved_count = 0
                    for question_id_str, result_data in transformed.items():
                        try:
                            question_id = int(question_id_str)
                            result_value = result_data.get("result", "fail")
                            reason = result_data.get("reason", "")
                            confidence_score = result_data.get("confidence_score", 5)

                            repository.create_audit_result(
                                question_id=question_id,
                                session_id=session_id,
                                result=result_value,
                                reason=reason,
                                confidence_score=confidence_score,
                            )
                            saved_count += 1
                        except (ValueError, TypeError):
                            pass
                        except Exception:
                            pass

                return transformed

            raise RuntimeError(f"OpenAI API error: {e}")

    def _transform_response(
        self,
        result_json: Dict[str, Any],
        questions: Dict[str, Dict[str, Any]],
        session_id: str,
        page_type: str,
    ) -> Dict[str, Any]:
        """
        Transform response from API format to desired format.

        Input format:
        {"results": [{"question_id": "1", "pass_fail": "FAIL", "answer": "...",
         "evidence": "...", "confidence_score_1_to_10": 6}]}

        Output format:
        {
          "1": {"result": "FAIL", "reason": "...", "confidence_score": 6},
          "2": {"result": "PASS", "reason": "...", "confidence_score": 9}
        }
        """
        transformed = {}

        results = result_json.get("results", [])

        q14_policy_data = None
        if "14" in questions:
            q14_policy_data = self._load_q14_policy_data(session_id, page_type)

        for idx, item in enumerate(results, 1):
            question_id = item.get("question_id", "")
            pass_fail = item.get("pass_fail", "FAIL")
            answer = item.get("answer", "")
            evidence = item.get("evidence", "")
            confidence_raw = item.get("confidence_score_1_to_10", 5)

            if pass_fail not in ["PASS", "FAIL", "UNKNOWN"]:
                pass_fail = "FAIL"

            try:
                confidence_score = int(confidence_raw)
            except (ValueError, TypeError):
                confidence_score = 5

            confidence_score = max(1, min(10, confidence_score))

            if question_id == "14" and q14_policy_data:
                pass_fail = self._apply_q14_policy_rule(
                    pass_fail, answer, evidence, q14_policy_data
                )

            reason = self._clean_reason(answer)

            question_key = str(question_id)
            if pass_fail == "PASS":
                result_value = "pass"
            elif pass_fail == "UNKNOWN":
                result_value = "unknown"
            else:
                result_value = "fail"

            transformed[question_key] = {
                "result": result_value,
                "reason": reason,
                "confidence_score": confidence_score,
            }

        return transformed

    def _clean_reason(self, text: str) -> str:
        """
        Remove chunk references and technical labels from reason text.

        Removes patterns like:
        - DESKTOP_HTML_CHUNK 01, DESKTOP_HTML_CHUNK 03, etc.
        - MOBILE_HTML_CHUNK 01, MOBILE_HTML_CHUNK 03, etc.
        - DESKTOP_VISIBLE_TEXT, MOBILE_VISIBLE_TEXT
        - DESKTOP_FEATURES_JSON, MOBILE_FEATURES_JSON
        - Any bracketed labels like [DESKTOP_HTML_CHUNK 03]
        """
        if not text:
            return ""

        import re

        cleaned = text

        patterns_to_remove = [
            r"DESKTOP_HTML_CHUNK\s+\d+",
            r"MOBILE_HTML_CHUNK\s+\d+",
            r"DESKTOP_VISIBLE_TEXT",
            r"MOBILE_VISIBLE_TEXT",
            r"DESKTOP_FEATURES_JSON",
            r"MOBILE_FEATURES_JSON",
            r"\[DESKTOP_HTML_CHUNK\s+\d+\]",
            r"\[MOBILE_HTML_CHUNK\s+\d+\]",
            r"\[DESKTOP_VISIBLE_TEXT\]",
            r"\[MOBILE_VISIBLE_TEXT\]",
            r"\[DESKTOP_FEATURES_JSON\]",
            r"\[MOBILE_FEATURES_JSON\]",
        ]

        for pattern in patterns_to_remove:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = cleaned.strip()

        cleaned = re.sub(r"[;,]+\s*", ", ", cleaned)
        cleaned = re.sub(r"\s*,\s*,+", ", ", cleaned)
        cleaned = cleaned.strip(" ,;")

        return cleaned

    def _load_q14_policy_data(self, session_id: str, page_type: str) -> Dict[str, str]:
        """Load visible text and features JSON for Q14 policy link checking."""
        data = {
            "desktop_visible_text": "",
            "mobile_visible_text": "",
            "desktop_features_json": "",
            "mobile_features_json": "",
        }

        for viewport in ["desktop", "mobile"]:
            visible_text = self.builder.load_artifact(
                session_id, page_type, viewport, "visible_text", include_screenshots=False
            )
            if visible_text:
                data[f"{viewport}_visible_text"] = visible_text

            features_json = self.builder.load_artifact(
                session_id, page_type, viewport, "features_json", include_screenshots=False
            )
            if features_json:
                data[f"{viewport}_features_json"] = features_json

        return data

    def _apply_q14_policy_rule(
        self, pass_fail: str, answer: str, evidence: str, policy_data: Dict[str, str]
    ) -> str:
        """
        Apply Q14 semantic policy matching rule.

        Returns PASS if all three policy links found, unless explicit evidence links are broken.
        """
        all_text = " ".join(
            [
                policy_data.get("desktop_visible_text", ""),
                policy_data.get("mobile_visible_text", ""),
                policy_data.get("desktop_features_json", ""),
                policy_data.get("mobile_features_json", ""),
            ]
        )

        has_return = PolicyLinkMatcher.has_return_policy_link(all_text)
        has_privacy = PolicyLinkMatcher.has_privacy_policy_link(all_text)
        has_terms = PolicyLinkMatcher.has_terms_link(all_text)

        if has_return and has_privacy and has_terms:
            evidence_lower = evidence.lower() if evidence else ""
            answer_lower = answer.lower() if answer else ""

            broken_indicators = ["broken", "404", "not found", "error", "invalid", "missing link"]
            has_broken_link = any(
                indicator in evidence_lower or indicator in answer_lower
                for indicator in broken_indicators
            )

            if not has_broken_link:
                return "PASS"

        return pass_fail
