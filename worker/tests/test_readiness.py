"""
Unit tests for page readiness timing, scroll sequence, and popup dismissal.

Covers: network idle + DOM stability + minimum wait windows per spec,
soft timeout behavior, scroll sequence, popup dismissal logging.
No network access required (offline tests with mocked Playwright).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from worker.crawl.constants import (
    DOM_STABILITY_TIMEOUT,
    MAX_DISMISSALS_PER_PASS,
    MINIMUM_WAIT_AFTER_LOAD,
    OVERLAY_HIDE_SETTLE_MS,
    SCROLL_WAIT,
)
from worker.crawl.readiness import (
    dismiss_popups,
    run_extraction_retry_prep,
    run_overlay_hide_fallback,
    scroll_sequence,
    wait_for_page_ready,
)


@pytest.mark.asyncio
async def test_wait_for_page_ready_success():
    """Test successful page ready with all timing milestones."""
    page = AsyncMock()
    page.wait_for_load_state = AsyncMock()

    timings = await wait_for_page_ready(page, soft_timeout=10000)

    # All timing fields present
    assert "navigation_start" in timings
    assert "network_idle" in timings
    assert "network_idle_duration_ms" in timings
    assert "dom_stable" in timings
    assert "ready" in timings
    assert "total_load_duration_ms" in timings
    assert "soft_timeout" in timings

    # Soft timeout is False (no timeout)
    assert timings["soft_timeout"] is False

    # Timestamps are ISO format
    assert datetime.fromisoformat(timings["navigation_start"])
    assert datetime.fromisoformat(timings["network_idle"])
    assert datetime.fromisoformat(timings["dom_stable"])
    assert datetime.fromisoformat(timings["ready"])

    # Durations are numeric
    assert isinstance(timings["network_idle_duration_ms"], (int, float))
    assert isinstance(timings["total_load_duration_ms"], (int, float))


@pytest.mark.asyncio
async def test_wait_for_page_ready_soft_timeout():
    """Test page ready with soft timeout; continues with warning."""
    page = AsyncMock()
    # Simulate timeout on wait_for_load_state
    page.wait_for_load_state = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))

    timings = await wait_for_page_ready(page, soft_timeout=5000)

    # Soft timeout flag is True
    assert timings["soft_timeout"] is True

    # navigation_start and ready are set
    assert timings["navigation_start"] is not None
    assert timings["ready"] is not None
    assert timings["total_load_duration_ms"] is not None

    # Unreached milestones are None
    assert timings["network_idle"] is None
    assert timings["network_idle_duration_ms"] is None
    assert timings["dom_stable"] is None


@pytest.mark.asyncio
async def test_wait_for_page_ready_timing_order():
    """Test that timing milestones are in chronological order."""
    page = AsyncMock()
    page.wait_for_load_state = AsyncMock()

    timings = await wait_for_page_ready(page, soft_timeout=10000)

    # Parse timestamps
    nav_start = datetime.fromisoformat(timings["navigation_start"])
    network_idle = datetime.fromisoformat(timings["network_idle"])
    dom_stable = datetime.fromisoformat(timings["dom_stable"])
    ready = datetime.fromisoformat(timings["ready"])

    # Chronological order: nav_start < network_idle < dom_stable < ready
    assert nav_start <= network_idle
    assert network_idle <= dom_stable
    assert dom_stable <= ready


@pytest.mark.asyncio
async def test_wait_for_page_ready_minimum_wait_enforced():
    """Test that minimum wait after load is enforced (2s spec)."""
    page = AsyncMock()
    page.wait_for_load_state = AsyncMock()

    start = datetime.now(timezone.utc)
    await wait_for_page_ready(page, soft_timeout=10000)
    end = datetime.now(timezone.utc)

    # Total duration should be at least DOM_STABILITY + MINIMUM_WAIT
    min_duration_ms = DOM_STABILITY_TIMEOUT + MINIMUM_WAIT_AFTER_LOAD
    elapsed_ms = (end - start).total_seconds() * 1000

    # Allow small tolerance for test execution overhead
    assert elapsed_ms >= min_duration_ms - 100


@pytest.mark.asyncio
async def test_wait_for_page_ready_key_set_consistent():
    """Test that timings dict has consistent keys regardless of success/timeout."""
    page_success = AsyncMock()
    page_success.wait_for_load_state = AsyncMock()

    page_timeout = AsyncMock()
    page_timeout.wait_for_load_state = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))

    timings_success = await wait_for_page_ready(page_success, soft_timeout=10000)
    timings_timeout = await wait_for_page_ready(page_timeout, soft_timeout=5000)

    # Same key set for both success and timeout
    assert set(timings_success.keys()) == set(timings_timeout.keys())
    expected_keys = {
        "navigation_start",
        "network_idle",
        "network_idle_duration_ms",
        "dom_stable",
        "ready",
        "total_load_duration_ms",
        "soft_timeout",
    }
    assert set(timings_success.keys()) == expected_keys


@pytest.mark.asyncio
async def test_scroll_sequence_order():
    """Test scroll sequence ends by returning to top."""
    page = AsyncMock()
    page.viewport_size = {"width": 1920, "height": 1080}
    page.evaluate = AsyncMock()

    await scroll_sequence(page)

    # Verify final scroll is back to top (0)
    calls = page.evaluate.call_args_list
    assert len(calls) >= 2
    assert "window.scrollTo(0, 0)" in calls[-1][0][0]


@pytest.mark.asyncio
async def test_scroll_sequence_waits_between_scrolls():
    """Test that scroll sequence includes waits after each scroll."""
    page = AsyncMock()
    page.viewport_size = {"width": 1920, "height": 1080}
    page.evaluate = AsyncMock()

    with patch("worker.crawl.readiness.asyncio.sleep") as mock_sleep:
        await scroll_sequence(page)

        # Verify sleeps occurred (scroll waits + bottom dwell + final top wait)
        assert mock_sleep.call_count >= 2


@pytest.mark.asyncio
async def test_scroll_sequence_handles_missing_viewport():
    """Test scroll sequence with no viewport size (uses default)."""
    page = AsyncMock()
    page.viewport_size = None  # Missing viewport
    page.evaluate = AsyncMock()

    await scroll_sequence(page)

    # Loop (scrollTo + at_bottom check) + scroll to bottom + scroll to top = at least 4
    assert page.evaluate.call_count >= 4


@pytest.mark.asyncio
async def test_dismiss_popups_success():
    """Test popup dismissal when popups are visible and pass safe-dismiss text check."""
    page = AsyncMock()

    # Mock locator chain for Accept button; must return safe-dismiss text
    locator_mock = MagicMock()
    locator_mock.first = AsyncMock()
    locator_mock.first.is_visible = AsyncMock(return_value=True)
    locator_mock.first.inner_text = AsyncMock(return_value="Accept")
    locator_mock.first.get_attribute = AsyncMock(return_value=None)
    locator_mock.first.evaluate = AsyncMock(return_value=True)
    locator_mock.first.click = AsyncMock()

    page.locator = MagicMock(return_value=locator_mock)

    events = await dismiss_popups(page)

    # At least one popup dismissed (event with result=success)
    assert isinstance(events, list)
    assert sum(1 for e in events if e.get("result") == "success") >= 1
    assert page.locator.call_count > 0


@pytest.mark.asyncio
async def test_dismiss_popups_none_visible():
    """Test popup dismissal when no popups are visible."""
    page = AsyncMock()

    # Mock locator that returns no visible elements
    locator_mock = MagicMock()
    locator_mock.first = AsyncMock()
    locator_mock.first.is_visible = AsyncMock(return_value=False)

    page.locator = MagicMock(return_value=locator_mock)

    events = await dismiss_popups(page)

    # No successful dismissals (events may include not_found/skipped)
    assert sum(1 for e in events if e.get("result") == "success") == 0


@pytest.mark.asyncio
async def test_dismiss_popups_continues_on_error():
    """Test popup dismissal continues on error (doesn't crash)."""
    page = AsyncMock()

    # First selector raises exception, second succeeds with safe-dismiss text
    locator_error = MagicMock()
    locator_error.first = AsyncMock()
    locator_error.first.is_visible = AsyncMock(side_effect=Exception("selector failed"))

    locator_success = MagicMock()
    locator_success.first = AsyncMock()
    locator_success.first.is_visible = AsyncMock(return_value=True)
    locator_success.first.inner_text = AsyncMock(return_value="Accept")
    locator_success.first.get_attribute = AsyncMock(return_value=None)
    locator_success.first.evaluate = AsyncMock(return_value=True)
    locator_success.first.click = AsyncMock()

    page.locator = MagicMock(side_effect=[locator_error, locator_success])

    events = await dismiss_popups(page)

    # Should continue past error and attempt remaining selectors; at least one success
    assert isinstance(events, list)
    assert sum(1 for e in events if e.get("result") == "success") >= 1


@pytest.mark.asyncio
async def test_dismiss_popups_logs_selector_and_timestamp():
    """Test popup events include selector, action, result, attempt, and timestamp for success."""
    page = AsyncMock()

    # Mock single visible popup with safe-dismiss text
    locator_mock = MagicMock()
    locator_mock.first = AsyncMock()
    locator_mock.first.is_visible = AsyncMock(side_effect=[True] + [False] * 20)
    locator_mock.first.inner_text = AsyncMock(return_value="Accept")
    locator_mock.first.get_attribute = AsyncMock(return_value=None)
    locator_mock.first.evaluate = AsyncMock(return_value=True)
    locator_mock.first.click = AsyncMock()

    page.locator = MagicMock(return_value=locator_mock)

    events = await dismiss_popups(page)

    successes = [e for e in events if e.get("result") == "success"]
    assert len(successes) >= 1

    first_success = successes[0]
    assert "selector" in first_success
    assert "action" in first_success
    assert "result" in first_success
    assert "attempt" in first_success
    assert "timestamp" in first_success
    assert datetime.fromisoformat(first_success["timestamp"])


@pytest.mark.asyncio
async def test_dismiss_popups_skips_risky_cta():
    """Test popup dismissal skips risky CTA text (buy/checkout/allow notifications)."""
    page = AsyncMock()

    locator_mock = MagicMock()
    locator_mock.first = AsyncMock()
    locator_mock.first.is_visible = AsyncMock(return_value=True)
    locator_mock.first.inner_text = AsyncMock(return_value="Buy now")
    locator_mock.first.get_attribute = AsyncMock(return_value=None)
    locator_mock.first.evaluate = AsyncMock(return_value=True)
    locator_mock.first.click = AsyncMock()

    page.locator = MagicMock(return_value=locator_mock)

    events = await dismiss_popups(page)

    # No click on risky CTA; no successful dismissals
    assert sum(1 for e in events if e.get("result") == "success") == 0
    locator_mock.first.click.assert_not_called()


@pytest.mark.asyncio
async def test_dismiss_popups_skips_non_safe_dismiss_text():
    """Test popup dismissal skips elements that do not match safe-dismiss keywords."""
    page = AsyncMock()

    locator_mock = MagicMock()
    locator_mock.first = AsyncMock()
    locator_mock.first.is_visible = AsyncMock(return_value=True)
    locator_mock.first.inner_text = AsyncMock(return_value="Learn more")
    locator_mock.first.get_attribute = AsyncMock(return_value=None)
    locator_mock.first.evaluate = AsyncMock(return_value=True)
    locator_mock.first.click = AsyncMock()

    page.locator = MagicMock(return_value=locator_mock)

    events = await dismiss_popups(page)

    # No click when text is not safe-dismiss; no successful dismissals
    assert sum(1 for e in events if e.get("result") == "success") == 0
    locator_mock.first.click.assert_not_called()


@pytest.mark.asyncio
async def test_dismiss_popups_max_dismissals_per_pass():
    """Test bounded attempts: at most MAX_DISMISSALS_PER_PASS successes per pass."""
    page = AsyncMock()
    # Every selector finds a visible, safe-dismiss element (Accept)
    locator_mock = MagicMock()
    locator_mock.first = AsyncMock()
    locator_mock.first.is_visible = AsyncMock(return_value=True)
    locator_mock.first.inner_text = AsyncMock(return_value="Accept")
    locator_mock.first.get_attribute = AsyncMock(return_value=None)
    locator_mock.first.evaluate = AsyncMock(return_value=True)
    locator_mock.first.click = AsyncMock()
    page.locator = MagicMock(return_value=locator_mock)

    events = await dismiss_popups(page)

    success_events = [e for e in events if e.get("result") == "success"]
    assert len(success_events) == MAX_DISMISSALS_PER_PASS
    assert locator_mock.first.click.call_count == MAX_DISMISSALS_PER_PASS


@pytest.mark.asyncio
async def test_dismiss_popups_attempt_numbers_sequential():
    """Test attempt numbers are 1-based and sequential for events in a pass."""
    page = AsyncMock()
    locator_mock = MagicMock()
    locator_mock.first = AsyncMock()
    locator_mock.first.is_visible = AsyncMock(return_value=True)
    locator_mock.first.inner_text = AsyncMock(return_value="Accept")
    locator_mock.first.get_attribute = AsyncMock(return_value=None)
    locator_mock.first.evaluate = AsyncMock(return_value=True)
    locator_mock.first.click = AsyncMock()
    page.locator = MagicMock(return_value=locator_mock)

    events = await dismiss_popups(page)

    success_events = [e for e in events if e.get("result") == "success"]
    assert len(success_events) == MAX_DISMISSALS_PER_PASS
    attempts = [e["attempt"] for e in success_events]
    assert attempts == list(range(1, MAX_DISMISSALS_PER_PASS + 1))


# --- Integration with wait_for_page_ready ---


@pytest.mark.asyncio
async def test_readiness_timings_deterministic():
    """Test that identical conditions produce consistent timing structure."""
    page = AsyncMock()
    page.wait_for_load_state = AsyncMock()

    timings1 = await wait_for_page_ready(page, soft_timeout=10000)
    timings2 = await wait_for_page_ready(page, soft_timeout=10000)

    # Same keys in both
    assert set(timings1.keys()) == set(timings2.keys())

    # Both have soft_timeout=False
    assert timings1["soft_timeout"] is False
    assert timings2["soft_timeout"] is False


@pytest.mark.asyncio
async def test_readiness_constants_match_spec():
    """Test that readiness constants match TECH_SPEC values."""
    # Per TECH_SPEC: network idle 800ms, DOM stability 1s, minimum wait 2s
    # These are defined in worker/crawl/constants.py
    assert DOM_STABILITY_TIMEOUT == 1000  # 1s in ms
    assert MINIMUM_WAIT_AFTER_LOAD == 2000  # 2s in ms
    assert SCROLL_WAIT == 2000  # 2s per scroll (matches constants.py)


# --- Overlay hide fallback (TECH_SPEC §5 v1.23) ---


@pytest.mark.asyncio
async def test_run_overlay_hide_fallback_returns_empty_when_not_blocked():
    """Fallback does not run when page is not blocked (e.g. dismiss already succeeded)."""
    with patch(
        "worker.crawl.readiness.detect_blocked_page",
        new_callable=AsyncMock,
        return_value={
            "is_blocked": False,
            "has_overlay_candidate": False,
            "scroll_locked": False,
            "click_blocked": False,
            "overlay_candidate_count": 0,
        },
    ):
        page = AsyncMock()
        page.url = "https://example.com/"
        events = await run_overlay_hide_fallback(page)
    assert events == []


@pytest.mark.asyncio
async def test_run_overlay_hide_fallback_runs_only_when_blocked():
    """Fallback runs only when blocked (A + B); returns one event with summary details."""
    with (
        patch(
            "worker.crawl.readiness.detect_blocked_page",
            new_callable=AsyncMock,
            return_value={
                "is_blocked": True,
                "has_overlay_candidate": True,
                "scroll_locked": True,
                "click_blocked": False,
                "overlay_candidate_count": 1,
            },
        ),
        patch(
            "worker.crawl.readiness.apply_overlay_hide_in_frames",
            new_callable=AsyncMock,
            return_value=(3, 2),
        ),
    ):
        page = AsyncMock()
        page.url = "https://example.com/"
        events = await run_overlay_hide_fallback(page)
    assert len(events) == 1
    ev = events[0]
    assert ev["action"] == "overlay_hide_fallback"
    assert ev["result"] == "success"
    assert ev["hidden_count"] == 3
    assert ev["frame_count"] == 2
    assert ev["scroll_locked"] is True
    assert ev["click_blocked"] is False
    assert "timestamp" in ev
    assert ev.get("current_url") == "https://example.com/"


@pytest.mark.asyncio
async def test_run_overlay_hide_fallback_result_failure_when_hidden_zero():
    """When fallback runs but hidden_count=0, result is failure."""
    with (
        patch(
            "worker.crawl.readiness.detect_blocked_page",
            new_callable=AsyncMock,
            return_value={
                "is_blocked": True,
                "has_overlay_candidate": True,
                "scroll_locked": True,
                "click_blocked": False,
                "overlay_candidate_count": 1,
            },
        ),
        patch(
            "worker.crawl.readiness.apply_overlay_hide_in_frames",
            new_callable=AsyncMock,
            return_value=(0, 1),
        ),
    ):
        page = AsyncMock()
        page.url = "https://example.com/"
        events = await run_overlay_hide_fallback(page)
    assert len(events) == 1
    assert events[0]["result"] == "failure"
    assert events[0]["hidden_count"] == 0


@pytest.mark.asyncio
async def test_run_overlay_hide_fallback_invokes_iframe_handling():
    """When blocked, apply_overlay_hide_in_frames (iframe handling) is invoked."""
    apply_mock = AsyncMock(return_value=(1, 2))
    with (
        patch(
            "worker.crawl.readiness.detect_blocked_page",
            new_callable=AsyncMock,
            return_value={
                "is_blocked": True,
                "has_overlay_candidate": True,
                "scroll_locked": False,
                "click_blocked": True,
                "overlay_candidate_count": 1,
            },
        ),
        patch("worker.crawl.readiness.apply_overlay_hide_in_frames", apply_mock),
    ):
        page = AsyncMock()
        page.url = "https://example.com/"
        await run_overlay_hide_fallback(page)
    apply_mock.assert_awaited_once_with(page)


@pytest.mark.asyncio
async def test_run_overlay_hide_fallback_logging_includes_overlay_hide_fallback():
    """Logging includes overlay_hide_fallback when fallback runs."""
    with (
        patch(
            "worker.crawl.readiness.detect_blocked_page",
            new_callable=AsyncMock,
            return_value={
                "is_blocked": True,
                "has_overlay_candidate": True,
                "scroll_locked": True,
                "click_blocked": False,
                "overlay_candidate_count": 1,
            },
        ),
        patch(
            "worker.crawl.readiness.apply_overlay_hide_in_frames",
            new_callable=AsyncMock,
            return_value=(2, 1),
        ),
        patch("worker.crawl.readiness.logger") as mock_logger,
    ):
        page = AsyncMock()
        page.url = "https://example.com/"
        await run_overlay_hide_fallback(page)
    mock_logger.info.assert_called_once()
    call_kwargs = mock_logger.info.call_args[1]
    assert call_kwargs.get("hidden_count") == 2
    assert call_kwargs.get("frame_count") == 1
    assert mock_logger.info.call_args[0][0] == "overlay_hide_fallback"


@pytest.mark.asyncio
async def test_run_overlay_hide_fallback_delay_applied_when_blocked():
    """Overlay hide settle delay only when fallback runs (TECH_SPEC §5 v1.24)."""
    with (
        patch(
            "worker.crawl.readiness.detect_blocked_page",
            new_callable=AsyncMock,
            return_value={
                "is_blocked": True,
                "has_overlay_candidate": True,
                "scroll_locked": False,
                "click_blocked": False,
                "overlay_candidate_count": 1,
            },
        ),
        patch(
            "worker.crawl.readiness.apply_overlay_hide_in_frames",
            new_callable=AsyncMock,
            return_value=(1, 1),
        ),
        patch("worker.crawl.readiness.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        page = AsyncMock()
        page.url = "https://example.com/"
        await run_overlay_hide_fallback(page)
    mock_sleep.assert_awaited_once_with(OVERLAY_HIDE_SETTLE_MS / 1000)


@pytest.mark.asyncio
async def test_run_overlay_hide_fallback_delay_not_applied_when_not_blocked():
    """When page is not blocked, no settle delay is applied (no asyncio.sleep)."""
    with (
        patch(
            "worker.crawl.readiness.detect_blocked_page",
            new_callable=AsyncMock,
            return_value={
                "is_blocked": False,
                "has_overlay_candidate": False,
                "scroll_locked": False,
                "click_blocked": False,
                "overlay_candidate_count": 0,
            },
        ),
        patch("worker.crawl.readiness.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        page = AsyncMock()
        page.url = "https://example.com/"
        await run_overlay_hide_fallback(page)
    mock_sleep.assert_not_called()


# --- Extraction retry prep (TECH_SPEC §5 v1.24) ---


@pytest.mark.asyncio
async def test_run_extraction_retry_prep_order_and_return():
    """Retry prep: wait_for_page_ready, dismiss_popups, overlay fallback; returns both lists."""
    wait_mock = AsyncMock(return_value={"ready": "ok"})
    popup_events = [{"action": "dismiss_click", "result": "success"}]
    overlay_events = [{"action": "overlay_hide_fallback"}]
    dismiss_mock = AsyncMock(return_value=popup_events)
    overlay_mock = AsyncMock(return_value=overlay_events)
    with (
        patch("worker.crawl.readiness.wait_for_page_ready", wait_mock),
        patch("worker.crawl.readiness.dismiss_popups", dismiss_mock),
        patch("worker.crawl.readiness.run_overlay_hide_fallback", overlay_mock),
    ):
        page = AsyncMock()
        result = await run_extraction_retry_prep(page, soft_timeout=3000)
    assert result == (popup_events, overlay_events)
    wait_mock.assert_awaited_once_with(page, soft_timeout=3000)
    dismiss_mock.assert_awaited_once_with(page)
    overlay_mock.assert_awaited_once_with(page)
