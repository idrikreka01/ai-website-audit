"""
Navigation retry helper: deterministic backoff, failure classification, bot-block mitigation.

Per TECH_SPEC_V1.1.md §5 Navigation retry policy (v1.3). All navigation attempts
(homepage, PDP, PDP candidate validation) go through navigate_with_retry.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from playwright.async_api import Page, Response
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from shared.logging import get_logger

if TYPE_CHECKING:
    from worker.repository import AuditRepository

logger = get_logger(__name__)

# Spec: max 3 attempts, backoff 1s / 2s / 4s, optional jitter 0–500 ms
MAX_NAV_ATTEMPTS = 3
BACKOFF_SECONDS = (1, 2, 4)
JITTER_MS = 500
# Per-attempt navigation timeout (ms); hard per-page timeout (ms)
NAV_TIMEOUT_MS = 30_000
HARD_PAGE_TIMEOUT_MS = 90_000
# Bot-block: wait 2 s then one reload
BOT_BLOCK_WAIT_SECONDS = 2

# Substrings that indicate challenge/captcha/block (case-insensitive)
BOT_BLOCK_INDICATORS = (
    "challenge",
    "captcha",
    "verify you are human",
    "access denied",
    "blocked",
    "bot",
)


@dataclass
class NavigateResult:
    """Result of navigate_with_retry."""

    success: bool
    response: Optional[Response]
    error_summary: Optional[str]
    bot_block_mitigation_used: bool = False


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff for attempt 1-based index; add jitter 0–500 ms."""
    base = BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)]
    jitter = random.uniform(0, JITTER_MS / 1000.0)
    return base + jitter


def _classify_failure(exc: BaseException) -> tuple[bool, str]:
    """
    Classify navigation failure as retryable or not.

    Returns (retryable, reason). Reason is one of: navigation_timeout, net_err,
    status_403_503, or non_retryable.
    """
    if isinstance(exc, PlaywrightTimeoutError):
        return True, "navigation_timeout"
    msg = (getattr(exc, "message", None) or str(exc)).lower()
    if "net::err_" in msg:
        return True, "net_err"
    return False, "non_retryable"


def _is_retryable_status(status: Optional[int]) -> bool:
    """Retry only on 403, 503, or 429 (rate-limit) per spec."""
    return status in (403, 503, 429)


def _retry_reason_for_status(status: int) -> str:
    """Logging reason for retryable status."""
    if status == 429:
        return "status_429"
    return "status_403_503"


async def is_bot_block_page(page: Page) -> bool:
    """
    Detect bot-block: challenge/captcha/block UI per spec.

    Treat as bot-block if title or body contains challenge, captcha,
    verify you are human, access denied, blocked, or bot.
    """
    try:
        title = await page.title()
        body_text = await page.inner_text("body")
        combined = f"{title} {body_text}".lower()
        return any(ind in combined for ind in BOT_BLOCK_INDICATORS)
    except Exception:
        return False


async def navigate_with_retry(
    page: Page,
    url: str,
    *,
    session_id: UUID,
    repository: Optional["AuditRepository"],
    page_type: str = "homepage",
    viewport: str = "desktop",
    domain: str = "",
    nav_timeout_ms: int = NAV_TIMEOUT_MS,
    hard_page_timeout_ms: int = HARD_PAGE_TIMEOUT_MS,
) -> NavigateResult:
    """
    Perform navigation with retries: max 3 attempts, backoff, failure classification,
    and at most one bot-block mitigation (wait 2 s + reload).

    Caller must pass repository when available so retries are logged to DB.
    """
    _repo = repository

    page_elapsed_ms = 0.0
    last_response: Optional[Response] = None
    bot_block_mitigation_used = False

    for attempt in range(1, MAX_NAV_ATTEMPTS + 1):
        logger.info(
            "navigation.attempt",
            attempt=attempt,
            url=url,
            session_id=str(session_id),
            page_type=page_type,
            viewport=viewport,
            domain=domain,
        )
        if _repo:
            _repo.create_log(
                session_id=session_id,
                level="info",
                event_type="navigation",
                message="Navigation attempt",
                details={
                    "attempt": attempt,
                    "url": url,
                    "page_type": page_type,
                    "viewport": viewport,
                    "domain": domain,
                },
            )

        if page_elapsed_ms >= hard_page_timeout_ms:
            logger.warning(
                "navigation.failed",
                attempt=attempt,
                url=url,
                session_id=str(session_id),
                page_type=page_type,
                viewport=viewport,
                domain=domain,
                failure_classification="hard_timeout",
                elapsed_ms=page_elapsed_ms,
            )
            if _repo:
                _repo.create_log(
                    session_id=session_id,
                    level="warn",
                    event_type="timeout",
                    message="Navigation failed",
                    details={
                        "attempt": attempt,
                        "failure_classification": "hard_timeout",
                        "url": url,
                        "page_type": page_type,
                        "viewport": viewport,
                        "elapsed_ms": page_elapsed_ms,
                    },
                )
            return NavigateResult(
                success=False,
                response=None,
                error_summary="Navigation timeout",
            )

        try:
            attempt_start = time.monotonic()
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=nav_timeout_ms,
            )
            page_elapsed_ms += (time.monotonic() - attempt_start) * 1000
            last_response = response

            if response is None:
                # Some navigations (e.g. about:blank) may not yield a response
                break

            status = response.status
            if _is_retryable_status(status) and attempt < MAX_NAV_ATTEMPTS:
                backoff = _backoff_seconds(attempt)
                reason_status = _retry_reason_for_status(status)
                logger.info(
                    "navigation.retry",
                    reason=reason_status,
                    attempt=attempt,
                    backoff_s=round(backoff, 2),
                    url=url,
                    session_id=str(session_id),
                    page_type=page_type,
                    viewport=viewport,
                    domain=domain,
                    status=status,
                    failure_classification=reason_status,
                )
                if _repo:
                    _repo.create_log(
                        session_id=session_id,
                        level="info",
                        event_type="retry",
                        message="Navigation retry",
                        details={
                            "reason": reason_status,
                            "failure_classification": reason_status,
                            "attempt": attempt,
                            "backoff_s": round(backoff, 2),
                            "url": url,
                            "status": status,
                            "page_type": page_type,
                            "viewport": viewport,
                            "domain": domain,
                        },
                    )
                await asyncio.sleep(backoff)
                page_elapsed_ms += backoff * 1000
                continue

            if _is_retryable_status(status) and attempt == MAX_NAV_ATTEMPTS:
                reason_status = _retry_reason_for_status(status)
                error_summary = "Rate limited (429)" if status == 429 else "Blocked (403/503)"
                logger.info(
                    "navigation.failed",
                    attempt=attempt,
                    url=url,
                    session_id=str(session_id),
                    page_type=page_type,
                    viewport=viewport,
                    domain=domain,
                    failure_classification=reason_status,
                    status=status,
                )
                if _repo:
                    _repo.create_log(
                        session_id=session_id,
                        level="info",
                        event_type="navigation",
                        message="Navigation failed",
                        details={
                            "attempt": attempt,
                            "failure_classification": reason_status,
                            "url": url,
                            "status": status,
                            "page_type": page_type,
                            "viewport": viewport,
                            "domain": domain,
                        },
                    )
                return NavigateResult(
                    success=False,
                    response=response,
                    error_summary=error_summary,
                )

            # Non-retryable 4xx/5xx: do not retry, log and fail the page (spec §5).
            if status >= 400 and not _is_retryable_status(status):
                logger.error(
                    "navigation.failed",
                    attempt=attempt,
                    url=url,
                    session_id=str(session_id),
                    page_type=page_type,
                    viewport=viewport,
                    domain=domain,
                    failure_classification="non_retryable_status",
                    status=status,
                )
                if _repo:
                    _repo.create_log(
                        session_id=session_id,
                        level="error",
                        event_type="error",
                        message="Navigation failed",
                        details={
                            "attempt": attempt,
                            "failure_classification": "non_retryable_status",
                            "url": url,
                            "status": status,
                            "page_type": page_type,
                            "viewport": viewport,
                            "domain": domain,
                        },
                    )
                return NavigateResult(
                    success=False,
                    response=response,
                    error_summary="Crawl failed",
                )

            # Success (2xx or other non-error status); check bot-block
            break

        except Exception as e:
            page_elapsed_ms += (time.monotonic() - attempt_start) * 1000
            retryable, reason = _classify_failure(e)
            if retryable and attempt < MAX_NAV_ATTEMPTS:
                backoff = _backoff_seconds(attempt)
                logger.info(
                    "navigation.retry",
                    reason=reason,
                    attempt=attempt,
                    backoff_s=round(backoff, 2),
                    url=url,
                    session_id=str(session_id),
                    page_type=page_type,
                    viewport=viewport,
                    domain=domain,
                    failure_classification=reason,
                    error=str(e),
                )
                if _repo:
                    _repo.create_log(
                        session_id=session_id,
                        level="info",
                        event_type="retry",
                        message="Navigation retry",
                        details={
                            "reason": reason,
                            "failure_classification": reason,
                            "attempt": attempt,
                            "backoff_s": round(backoff, 2),
                            "url": url,
                            "page_type": page_type,
                            "viewport": viewport,
                            "domain": domain,
                            "error": str(e),
                        },
                    )
                await asyncio.sleep(backoff)
                page_elapsed_ms += backoff * 1000
                continue
            # Non-retryable or last attempt
            logger.error(
                "navigation.failed",
                reason=reason,
                attempt=attempt,
                url=url,
                session_id=str(session_id),
                page_type=page_type,
                viewport=viewport,
                domain=domain,
                failure_classification=reason,
                error=str(e),
            )
            if _repo:
                _repo.create_log(
                    session_id=session_id,
                    level="error",
                    event_type=("timeout" if reason == "navigation_timeout" else "error"),
                    message="Navigation failed",
                    details={
                        "reason": reason,
                        "failure_classification": reason,
                        "attempt": attempt,
                        "url": url,
                        "page_type": page_type,
                        "viewport": viewport,
                        "domain": domain,
                        "error": str(e),
                    },
                )
            return NavigateResult(
                success=False,
                response=None,
                error_summary=(
                    "Navigation timeout" if reason == "navigation_timeout" else "Crawl failed"
                ),
            )

    # Successful load (or response None). Check bot-block; at most one mitigation.
    if last_response is None:
        logger.info(
            "navigation.success",
            attempt=attempt,
            url=url,
            session_id=str(session_id),
            page_type=page_type,
            viewport=viewport,
            domain=domain,
        )
        if _repo:
            _repo.create_log(
                session_id=session_id,
                level="info",
                event_type="navigation",
                message="Navigation success",
                details={
                    "attempt": attempt,
                    "url": url,
                    "page_type": page_type,
                    "viewport": viewport,
                    "domain": domain,
                },
            )
        return NavigateResult(success=True, response=None, error_summary=None)

    if await is_bot_block_page(page):
        if not bot_block_mitigation_used:
            logger.info(
                "bot_block_detected",
                url=url,
                session_id=str(session_id),
                page_type=page_type,
                viewport=viewport,
                domain=domain,
            )
            if _repo:
                _repo.create_log(
                    session_id=session_id,
                    level="info",
                    event_type="retry",
                    message="Bot-block detected; single mitigation retry",
                    details={
                        "url": url,
                        "reason": "bot_block",
                        "page_type": page_type,
                        "viewport": viewport,
                        "domain": domain,
                    },
                )
            await asyncio.sleep(BOT_BLOCK_WAIT_SECONDS)
            try:
                start = time.monotonic()
                await page.reload(wait_until="domcontentloaded", timeout=nav_timeout_ms)
                page_elapsed_ms += (time.monotonic() - start) * 1000
            except Exception as e:
                logger.warning(
                    "navigation.failed",
                    url=url,
                    session_id=str(session_id),
                    page_type=page_type,
                    viewport=viewport,
                    domain=domain,
                    failure_classification="bot_block_reload_failed",
                    error=str(e),
                )
                if _repo:
                    _repo.create_log(
                        session_id=session_id,
                        level="warn",
                        event_type="error",
                        message="Navigation failed",
                        details={
                            "failure_classification": "bot_block_reload_failed",
                            "url": url,
                            "page_type": page_type,
                            "viewport": viewport,
                            "domain": domain,
                            "error": str(e),
                        },
                    )
                return NavigateResult(
                    success=False,
                    response=last_response,
                    error_summary="Bot-block; reload failed",
                    bot_block_mitigation_used=True,
                )
            bot_block_mitigation_used = True
            if await is_bot_block_page(page):
                logger.info(
                    "navigation.failed",
                    url=url,
                    session_id=str(session_id),
                    page_type=page_type,
                    viewport=viewport,
                    domain=domain,
                    failure_classification="bot_block",
                )
                if _repo:
                    _repo.create_log(
                        session_id=session_id,
                        level="info",
                        event_type="navigation",
                        message="Navigation failed",
                        details={
                            "failure_classification": "bot_block",
                            "url": url,
                            "page_type": page_type,
                            "viewport": viewport,
                            "domain": domain,
                        },
                    )
                return NavigateResult(
                    success=False,
                    response=last_response,
                    error_summary="Bot-block",
                    bot_block_mitigation_used=True,
                )
        else:
            logger.info(
                "navigation.failed",
                url=url,
                session_id=str(session_id),
                page_type=page_type,
                viewport=viewport,
                domain=domain,
                failure_classification="bot_block",
            )
            if _repo:
                _repo.create_log(
                    session_id=session_id,
                    level="info",
                    event_type="navigation",
                    message="Navigation failed",
                    details={
                        "failure_classification": "bot_block",
                        "url": url,
                        "page_type": page_type,
                        "viewport": viewport,
                        "domain": domain,
                    },
                )
            return NavigateResult(
                success=False,
                response=last_response,
                error_summary="Bot-block",
                bot_block_mitigation_used=True,
            )

    logger.info(
        "navigation.success",
        attempt=attempt,
        url=url,
        session_id=str(session_id),
        page_type=page_type,
        viewport=viewport,
        domain=domain,
        bot_block_mitigation_used=bot_block_mitigation_used,
    )
    if _repo:
        _repo.create_log(
            session_id=session_id,
            level="info",
            event_type="navigation",
            message="Navigation success",
            details={
                "attempt": attempt,
                "url": url,
                "page_type": page_type,
                "viewport": viewport,
                "domain": domain,
                "bot_block_mitigation_used": bot_block_mitigation_used,
            },
        )
    return NavigateResult(
        success=True,
        response=last_response,
        error_summary=None,
        bot_block_mitigation_used=bot_block_mitigation_used,
    )
