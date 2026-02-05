"""
Unit tests for blocked-page detection and overlay hide (TECH_SPEC_V1.1.md §5 v1.23).

Covers: detection logic (A + B), is_page_blocked, apply_overlay_hide_in_frames.
No Playwright browser required; page.evaluate and frames are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from worker.crawl.blocked_page import (
    apply_overlay_hide_in_frames,
    detect_blocked_page,
    is_page_blocked,
)


def _raw_blocked(
    has_overlay=True,
    scroll_locked=True,
    click_blocked=False,
    overlay_count=1,
):
    """Raw evaluate result: isBlocked = hasOverlayCandidate && (scrollLocked || clickBlocked)."""
    return {
        "hasOverlayCandidate": has_overlay,
        "scrollLocked": scroll_locked,
        "clickBlocked": click_blocked,
        "isBlocked": has_overlay and (scroll_locked or click_blocked),
        "overlayCandidateCount": overlay_count if has_overlay else 0,
    }


@pytest.mark.asyncio
async def test_detect_blocked_page_blocked_when_a_and_b():
    """Blocked only when overlay heuristic (A) and blocking signal (B) both true."""
    page = AsyncMock()
    page.evaluate = AsyncMock(
        return_value=_raw_blocked(has_overlay=True, scroll_locked=True, click_blocked=False)
    )
    result = await detect_blocked_page(page)
    assert result["is_blocked"] is True
    assert result["has_overlay_candidate"] is True
    assert result["scroll_locked"] is True
    assert result["click_blocked"] is False
    assert result["overlay_candidate_count"] == 1


@pytest.mark.asyncio
async def test_detect_blocked_page_blocked_when_click_blocked():
    """Blocked when overlay + click-blocked (no scroll lock)."""
    page = AsyncMock()
    page.evaluate = AsyncMock(
        return_value=_raw_blocked(has_overlay=True, scroll_locked=False, click_blocked=True)
    )
    result = await detect_blocked_page(page)
    assert result["is_blocked"] is True
    assert result["click_blocked"] is True
    assert result["scroll_locked"] is False


@pytest.mark.asyncio
async def test_detect_blocked_page_not_blocked_when_no_overlay():
    """Not blocked when no overlay candidate (B may be true but A false)."""
    page = AsyncMock()
    page.evaluate = AsyncMock(
        return_value=_raw_blocked(
            has_overlay=False,
            overlay_count=0,
            scroll_locked=True,
            click_blocked=False,
        )
    )
    result = await detect_blocked_page(page)
    assert result["is_blocked"] is False
    assert result["has_overlay_candidate"] is False
    assert result["overlay_candidate_count"] == 0


@pytest.mark.asyncio
async def test_detect_blocked_page_not_blocked_when_overlay_but_no_blocking_signal():
    """Not blocked when overlay present but neither scroll lock nor click blocked (A but not B)."""
    page = AsyncMock()
    page.evaluate = AsyncMock(
        return_value=_raw_blocked(
            has_overlay=True,
            scroll_locked=False,
            click_blocked=False,
        )
    )
    result = await detect_blocked_page(page)
    assert result["is_blocked"] is False
    assert result["has_overlay_candidate"] is True
    assert result["scroll_locked"] is False
    assert result["click_blocked"] is False


@pytest.mark.asyncio
async def test_is_page_blocked_true():
    """is_page_blocked returns True when detect_blocked_page says blocked."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=_raw_blocked(has_overlay=True, scroll_locked=True))
    assert await is_page_blocked(page) is True


@pytest.mark.asyncio
async def test_is_page_blocked_false():
    """is_page_blocked returns False when detect_blocked_page says not blocked."""
    page = AsyncMock()
    page.evaluate = AsyncMock(
        return_value=_raw_blocked(has_overlay=False, overlay_count=0, scroll_locked=False)
    )
    assert await is_page_blocked(page) is False


@pytest.mark.asyncio
async def test_apply_overlay_hide_in_frames_invokes_evaluate_per_frame():
    """Iframe handling: evaluate once per frame; frame_count and hidden_count aggregated."""
    frame1 = AsyncMock()
    frame1.evaluate = AsyncMock(return_value={"hiddenCount": 2})
    frame2 = AsyncMock()
    frame2.evaluate = AsyncMock(return_value={"hiddenCount": 1})
    page = MagicMock()
    page.frames = [frame1, frame2]

    total_hidden, frame_count = await apply_overlay_hide_in_frames(page)

    assert total_hidden == 3
    assert frame_count == 2
    assert frame1.evaluate.await_count == 1
    assert frame2.evaluate.await_count == 1


@pytest.mark.asyncio
async def test_apply_overlay_hide_in_frames_skips_failing_frame():
    """Frames that raise on evaluate are skipped; only successful frames counted."""
    frame1 = AsyncMock()
    frame1.evaluate = AsyncMock(return_value={"hiddenCount": 1})
    frame2 = AsyncMock()
    frame2.evaluate = AsyncMock(side_effect=Exception("cross-origin"))
    page = MagicMock()
    page.frames = [frame1, frame2]

    total_hidden, frame_count = await apply_overlay_hide_in_frames(page)

    assert total_hidden == 1
    assert frame_count == 1
