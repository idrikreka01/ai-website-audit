"""
Unit tests for navigation retry policy: max attempts, backoff, failure classification, bot-block.

Per TECH_SPEC_V1.1.md §5 Navigation retry policy (v1.3). No Playwright/network required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from worker.crawl.navigation_retry import (
    BACKOFF_SECONDS,
    MAX_NAV_ATTEMPTS,
    _backoff_seconds,
    _classify_failure,
    _is_retryable_status,
    _retry_reason_for_status,
    is_bot_block_page,
    navigate_with_retry,
)

# --- Max attempts and backoff ---


def test_backoff_seconds_max_attempts_constants():
    """Max 3 attempts per spec; backoff base 1s, 2s, 4s."""
    assert MAX_NAV_ATTEMPTS == 3
    assert BACKOFF_SECONDS == (1, 2, 4)


def test_backoff_seconds_in_range_for_attempts_1_2_3():
    """Backoff for attempts 1–3 is base (1s, 2s, 4s) plus jitter 0–500 ms."""
    for attempt in (1, 2, 3):
        base = BACKOFF_SECONDS[attempt - 1]
        for _ in range(20):
            got = _backoff_seconds(attempt)
            assert base <= got <= base + 0.5, f"attempt={attempt} got={got}"


def test_backoff_seconds_attempt_beyond_three_uses_last_base():
    """Attempt > 3 still uses last backoff base (4s) plus jitter."""
    for attempt in (4, 5, 10):
        got = _backoff_seconds(attempt)
        assert 4 <= got <= 4.5, f"attempt={attempt} got={got}"


# --- Failure classification ---


def test_classify_failure_timeout_retryable():
    """Playwright TimeoutError is retryable, reason navigation_timeout."""
    exc = PlaywrightTimeoutError("Timeout 30000ms exceeded")
    retryable, reason = _classify_failure(exc)
    assert retryable is True
    assert reason == "navigation_timeout"


def test_classify_failure_net_err_retryable():
    """Exception message containing net::ERR_* is retryable, reason net_err."""

    class NetErr(Exception):
        message = "net::ERR_CONNECTION_REFUSED"

    retryable, reason = _classify_failure(NetErr())
    assert retryable is True
    assert reason == "net_err"

    retryable2, reason2 = _classify_failure(Exception("net::ERR_TIMED_OUT"))
    assert retryable2 is True
    assert reason2 == "net_err"


def test_classify_failure_non_retryable():
    """Other exceptions are non-retryable."""
    retryable, reason = _classify_failure(ValueError("bad url"))
    assert retryable is False
    assert reason == "non_retryable"

    retryable2, reason2 = _classify_failure(RuntimeError("Crawl failed"))
    assert retryable2 is False
    assert reason2 == "non_retryable"


# --- Retryable status (403, 503, 429) ---


def test_is_retryable_status_403_503_429():
    """403, 503, 429 are retryable per spec."""
    assert _is_retryable_status(403) is True
    assert _is_retryable_status(503) is True
    assert _is_retryable_status(429) is True


def test_is_retryable_status_4xx_5xx_other_not_retryable():
    """4xx (other than 403, 429) and 5xx (other than 503) are not retryable."""
    assert _is_retryable_status(404) is False
    assert _is_retryable_status(400) is False
    assert _is_retryable_status(500) is False
    assert _is_retryable_status(502) is False
    assert _is_retryable_status(200) is False
    assert _is_retryable_status(None) is False


def test_retry_reason_for_status_429_vs_403_503():
    """429 maps to status_429; 403/503 map to status_403_503."""
    assert _retry_reason_for_status(429) == "status_429"
    assert _retry_reason_for_status(403) == "status_403_503"
    assert _retry_reason_for_status(503) == "status_403_503"


# --- Bot-block detection ---


@pytest.mark.asyncio
async def test_is_bot_block_page_detects_challenge_captcha():
    """Page with strong bot-block indicators (per BOT_BLOCK_STRONG_INDICATORS) is detected."""
    # Current indicators: captcha, verify you are human, ddos protection
    page1 = AsyncMock()
    page1.title = AsyncMock(return_value="Please complete the captcha")
    page1.inner_text = AsyncMock(return_value="Verify you are human")
    assert await is_bot_block_page(page1) is True

    page2 = AsyncMock()
    page2.title = AsyncMock(return_value="Shop")
    page2.inner_text = AsyncMock(return_value="Verify you are human to continue")
    assert await is_bot_block_page(page2) is True

    page3 = AsyncMock()
    page3.title = AsyncMock(return_value="Blocked")
    page3.inner_text = AsyncMock(return_value="DDoS protection active")
    assert await is_bot_block_page(page3) is True


@pytest.mark.asyncio
async def test_is_bot_block_page_normal_page_false():
    """Page without bot-block indicators returns False."""
    page = AsyncMock()
    page.title = AsyncMock(return_value="Product Page")
    page.inner_text = AsyncMock(return_value="Add to cart, price, description")

    assert await is_bot_block_page(page) is False


@pytest.mark.asyncio
async def test_is_bot_block_page_exception_returns_false():
    """If title/body access fails, treat as not bot-block (safe fallback)."""
    page = AsyncMock()
    page.title = AsyncMock(side_effect=Exception("DOM error"))
    page.inner_text = AsyncMock(return_value="")

    assert await is_bot_block_page(page) is False


# --- navigate_with_retry: success and max attempts ---


@pytest.mark.asyncio
async def test_navigate_with_retry_success_first_attempt():
    """Success on first attempt returns success, no retries."""
    page = AsyncMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__bool__ = lambda self: True
    page.goto = AsyncMock(return_value=mock_response)

    with patch(
        "worker.crawl.navigation_retry.is_bot_block_page",
        new_callable=AsyncMock,
        return_value=False,
    ):
        result = await navigate_with_retry(
            page,
            "https://example.com/",
            session_id=uuid4(),
            repository=None,
            page_type="homepage",
            viewport="desktop",
            domain="example.com",
            nav_timeout_ms=500,
            hard_page_timeout_ms=5000,
        )

    assert result.success is True
    assert result.error_summary is None
    assert result.response is mock_response
    assert page.goto.await_count == 1


@pytest.mark.asyncio
async def test_navigate_with_retry_timeout_then_success():
    """Timeout on attempt 1, success on attempt 2 (retry with backoff)."""
    page = AsyncMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__bool__ = lambda self: True
    page.goto = AsyncMock(side_effect=[PlaywrightTimeoutError("timeout"), mock_response])

    with (
        patch("worker.crawl.navigation_retry.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "worker.crawl.navigation_retry.is_bot_block_page",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        result = await navigate_with_retry(
            page,
            "https://example.com/",
            session_id=uuid4(),
            repository=None,
            page_type="homepage",
            viewport="desktop",
            domain="example.com",
            nav_timeout_ms=100,
            hard_page_timeout_ms=10000,
        )

    assert result.success is True
    assert result.error_summary is None
    assert page.goto.await_count == 2


@pytest.mark.asyncio
async def test_navigate_with_retry_max_attempts_exhausted_timeout():
    """Three timeouts → failure, error_summary Navigation timeout."""
    page = AsyncMock()
    page.goto = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))

    with (
        patch("worker.crawl.navigation_retry.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "worker.crawl.navigation_retry.is_bot_block_page",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        result = await navigate_with_retry(
            page,
            "https://example.com/",
            session_id=uuid4(),
            repository=None,
            page_type="homepage",
            viewport="desktop",
            domain="example.com",
            nav_timeout_ms=50,
            hard_page_timeout_ms=10000,
        )

    assert result.success is False
    assert result.error_summary == "Navigation timeout"
    assert result.response is None
    assert page.goto.await_count == MAX_NAV_ATTEMPTS


@pytest.mark.asyncio
async def test_navigate_with_retry_403_then_success():
    """403 on attempt 1, success on attempt 2 (retryable status)."""
    page = AsyncMock()
    resp_403 = MagicMock()
    resp_403.status = 403
    resp_403.__bool__ = lambda self: True
    resp_200 = MagicMock()
    resp_200.status = 200
    resp_200.__bool__ = lambda self: True
    page.goto = AsyncMock(side_effect=[resp_403, resp_200])

    with (
        patch("worker.crawl.navigation_retry.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "worker.crawl.navigation_retry.is_bot_block_page",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        result = await navigate_with_retry(
            page,
            "https://example.com/",
            session_id=uuid4(),
            repository=None,
            page_type="homepage",
            viewport="desktop",
            domain="example.com",
            nav_timeout_ms=100,
            hard_page_timeout_ms=10000,
        )

    assert result.success is True
    assert page.goto.await_count == 2


@pytest.mark.asyncio
async def test_navigate_with_retry_429_three_times_fails():
    """429 on all three attempts → failure, error_summary Rate limited (429)."""
    page = AsyncMock()
    resp_429 = MagicMock()
    resp_429.status = 429
    resp_429.__bool__ = lambda self: True
    page.goto = AsyncMock(return_value=resp_429)

    with (
        patch("worker.crawl.navigation_retry.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "worker.crawl.navigation_retry.is_bot_block_page",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        result = await navigate_with_retry(
            page,
            "https://example.com/",
            session_id=uuid4(),
            repository=None,
            page_type="pdp",
            viewport="desktop",
            domain="example.com",
            nav_timeout_ms=100,
            hard_page_timeout_ms=10000,
        )

    assert result.success is False
    assert result.error_summary == "Rate limited (429)"
    assert page.goto.await_count == MAX_NAV_ATTEMPTS


@pytest.mark.asyncio
async def test_navigate_with_retry_404_non_retryable_log_and_fail():
    """404 is non-retryable per spec; do not retry, log and fail the page."""
    page = AsyncMock()
    resp_404 = MagicMock()
    resp_404.status = 404
    resp_404.__bool__ = lambda self: True
    page.goto = AsyncMock(return_value=resp_404)

    with patch(
        "worker.crawl.navigation_retry.is_bot_block_page",
        new_callable=AsyncMock,
        return_value=False,
    ):
        result = await navigate_with_retry(
            page,
            "https://example.com/404",
            session_id=uuid4(),
            repository=None,
            page_type="homepage",
            viewport="desktop",
            domain="example.com",
            nav_timeout_ms=100,
            hard_page_timeout_ms=10000,
        )

    assert result.success is False
    assert result.error_summary == "Crawl failed"
    assert result.response is resp_404
    assert page.goto.await_count == 1


@pytest.mark.asyncio
async def test_navigate_with_retry_500_non_retryable_log_and_fail():
    """500 (other than 503) is non-retryable per spec; log and fail the page."""
    page = AsyncMock()
    resp_500 = MagicMock()
    resp_500.status = 500
    resp_500.__bool__ = lambda self: True
    page.goto = AsyncMock(return_value=resp_500)

    with patch(
        "worker.crawl.navigation_retry.is_bot_block_page",
        new_callable=AsyncMock,
        return_value=False,
    ):
        result = await navigate_with_retry(
            page,
            "https://example.com/error",
            session_id=uuid4(),
            repository=None,
            page_type="pdp",
            viewport="desktop",
            domain="example.com",
            nav_timeout_ms=100,
            hard_page_timeout_ms=10000,
        )

    assert result.success is False
    assert result.error_summary == "Crawl failed"
    assert result.response is resp_500
    assert page.goto.await_count == 1


# --- Bot-block: one mitigation only ---


@pytest.mark.asyncio
async def test_navigate_with_retry_bot_block_one_mitigation_then_success():
    """Bot-block detected → one reload (mitigation) → not bot-block → success."""
    page = AsyncMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__bool__ = lambda self: True
    page.goto = AsyncMock(return_value=mock_response)
    page.reload = AsyncMock(return_value=None)

    is_bot_block_calls = [True, False]  # first load: bot-block; after reload: not

    async def bot_block_side_effect(*args, **kwargs):
        return is_bot_block_calls.pop(0) if is_bot_block_calls else False

    with (
        patch("worker.crawl.navigation_retry.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "worker.crawl.navigation_retry.is_bot_block_page",
            new_callable=AsyncMock,
            side_effect=bot_block_side_effect,
        ),
    ):
        result = await navigate_with_retry(
            page,
            "https://example.com/",
            session_id=uuid4(),
            repository=None,
            page_type="homepage",
            viewport="desktop",
            domain="example.com",
            nav_timeout_ms=100,
            hard_page_timeout_ms=10000,
        )

    assert result.success is True
    assert result.bot_block_mitigation_used is True
    assert result.error_summary is None
    assert page.goto.await_count == 1
    assert page.reload.await_count == 1


@pytest.mark.asyncio
async def test_navigate_with_retry_bot_block_one_mitigation_still_blocked_fails():
    """Bot-block → one reload → still bot-block → failure (no second mitigation)."""
    page = AsyncMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__bool__ = lambda self: True
    page.goto = AsyncMock(return_value=mock_response)
    page.reload = AsyncMock(return_value=None)

    with (
        patch("worker.crawl.navigation_retry.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "worker.crawl.navigation_retry.is_bot_block_page",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        result = await navigate_with_retry(
            page,
            "https://example.com/",
            session_id=uuid4(),
            repository=None,
            page_type="homepage",
            viewport="desktop",
            domain="example.com",
            nav_timeout_ms=100,
            hard_page_timeout_ms=10000,
        )

    assert result.success is False
    assert result.error_summary == "Bot-block"
    assert result.bot_block_mitigation_used is True
    assert page.goto.await_count == 1
    assert page.reload.await_count == 1


@pytest.mark.asyncio
async def test_navigate_with_retry_bot_block_reload_fails():
    """Bot-block → reload throws → failure, error_summary Bot-block; reload failed."""
    page = AsyncMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__bool__ = lambda self: True
    page.goto = AsyncMock(return_value=mock_response)
    page.reload = AsyncMock(side_effect=Exception("reload failed"))

    with (
        patch("worker.crawl.navigation_retry.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "worker.crawl.navigation_retry.is_bot_block_page",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        result = await navigate_with_retry(
            page,
            "https://example.com/",
            session_id=uuid4(),
            repository=None,
            page_type="homepage",
            viewport="desktop",
            domain="example.com",
            nav_timeout_ms=100,
            hard_page_timeout_ms=10000,
        )

    assert result.success is False
    assert result.error_summary == "Bot-block; reload failed"
    assert result.bot_block_mitigation_used is True
    assert page.reload.await_count == 1
