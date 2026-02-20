"""
Unit tests for session status computation and low-confidence rollup.

Rollup: True if any page has non-empty low_confidence_reasons. No logic change to session_status.py.
"""

from __future__ import annotations

from worker.session_status import compute_session_status, session_low_confidence_from_pages

PDP_URL = "https://example.com/p/1"
PARTIAL_MSG = "One or more viewports failed"


def test_pdp_not_found_homepage_succeeds_partial():
    """PDP not found but homepage both viewports succeed → partial, PDP not found."""
    status, summary = compute_session_status(
        home_desktop_success=True,
        home_mobile_success=True,
        pdp_desktop_success=False,
        pdp_mobile_success=False,
        pdp_url=None,
    )
    assert status == "partial"
    assert summary == "PDP not found"


def test_pdp_not_found_homepage_fails_failed():
    """PDP not found and homepage one or both fail → failed."""
    status, summary = compute_session_status(
        home_desktop_success=False,
        home_mobile_success=False,
        pdp_desktop_success=False,
        pdp_mobile_success=False,
        pdp_url=None,
    )
    assert status == "failed"
    assert summary == "All viewports failed"

    status2, summary2 = compute_session_status(
        home_desktop_success=True,
        home_mobile_success=False,
        pdp_desktop_success=False,
        pdp_mobile_success=False,
        pdp_url=None,
    )
    assert status2 == "failed"
    assert summary2 == "All viewports failed"


def test_pdp_present_all_succeed_completed():
    """PDP present and all four viewports succeed → completed."""
    status, summary = compute_session_status(
        home_desktop_success=True,
        home_mobile_success=True,
        pdp_desktop_success=True,
        pdp_mobile_success=True,
        pdp_url="https://example.com/p/1",
    )
    assert status == "completed"
    assert summary is None


def test_pdp_present_some_fail_partial():
    """PDP present and one or more viewports fail → partial."""
    status, summary = compute_session_status(
        home_desktop_success=True,
        home_mobile_success=True,
        pdp_desktop_success=True,
        pdp_mobile_success=False,
        pdp_url="https://example.com/p/1",
    )
    assert status == "partial"
    assert summary == "One or more viewports failed"


def test_pdp_present_all_fail_failed():
    """PDP present and all four fail → failed."""
    status, summary = compute_session_status(
        home_desktop_success=False,
        home_mobile_success=False,
        pdp_desktop_success=False,
        pdp_mobile_success=False,
        pdp_url="https://example.com/p/1",
    )
    assert status == "failed"
    assert summary == "All viewports failed"


def test_session_low_confidence_from_pages_true():
    """Session low_confidence True when any page has low_confidence_reasons."""
    pages = [
        {"low_confidence_reasons": []},
        {"low_confidence_reasons": ["missing_h1"]},
    ]
    assert session_low_confidence_from_pages(pages) is True


def test_session_low_confidence_from_pages_false():
    """Session low_confidence False when no page has reasons."""
    pages = [
        {"low_confidence_reasons": []},
        {},
    ]
    assert session_low_confidence_from_pages(pages) is False


# --- Rollup: any page with reasons => True ---


def test_session_low_confidence_rollup_any_page_has_reasons():
    """Rollup returns True if any page has non-empty low_confidence_reasons."""
    pages = [
        {"low_confidence_reasons": []},
        {"low_confidence_reasons": ["missing_h1"]},
        {"low_confidence_reasons": []},
    ]
    assert session_low_confidence_from_pages(pages) is True


def test_session_low_confidence_rollup_single_page_with_reasons():
    """Single page with one reason is enough for rollup True."""
    pages = [{"low_confidence_reasons": ["missing_primary_cta"]}]
    assert session_low_confidence_from_pages(pages) is True


def test_session_low_confidence_rollup_all_empty_false():
    """Rollup False when all pages have empty or missing reasons."""
    assert session_low_confidence_from_pages([]) is False
    assert session_low_confidence_from_pages([{"low_confidence_reasons": []}]) is False
    assert session_low_confidence_from_pages([{}, {}]) is False
    assert session_low_confidence_from_pages([{"low_confidence_reasons": []}, {}]) is False


def test_session_low_confidence_rollup_missing_key_treated_empty():
    """Page without low_confidence_reasons key is treated as no reasons (get default [])."""
    pages = [{"other": "data"}]  # no low_confidence_reasons key
    assert session_low_confidence_from_pages(pages) is False


# --- Status transition exhaustive tests ---


def test_compute_session_status_all_combinations():
    """Test all 32 combinations of 4 viewport success flags + pdp_url present/absent."""
    # Format: (home_d, home_m, pdp_d, pdp_m, pdp_url, expected_status, expected_summary_substr)
    test_cases = [
        # No PDP URL (PDP not found)
        (False, False, False, False, None, "failed", "All viewports failed"),
        (True, False, False, False, None, "failed", "All viewports failed"),
        (False, True, False, False, None, "failed", "All viewports failed"),
        (True, True, False, False, None, "partial", "PDP not found"),
        (False, False, True, False, None, "failed", "All viewports failed"),  # pdp flags ignored
        (True, False, True, False, None, "failed", "All viewports failed"),
        (False, True, True, False, None, "failed", "All viewports failed"),
        (True, True, True, False, None, "partial", "PDP not found"),
        (False, False, False, True, None, "failed", "All viewports failed"),
        (True, False, False, True, None, "failed", "All viewports failed"),
        (False, True, False, True, None, "failed", "All viewports failed"),
        (True, True, False, True, None, "partial", "PDP not found"),
        (False, False, True, True, None, "failed", "All viewports failed"),
        (True, False, True, True, None, "failed", "All viewports failed"),
        (False, True, True, True, None, "failed", "All viewports failed"),
        (True, True, True, True, None, "partial", "PDP not found"),
        # PDP URL present (PDP found)
        (False, False, False, False, PDP_URL, "failed", "All viewports failed"),
        (True, False, False, False, PDP_URL, "partial", PARTIAL_MSG),
        (False, True, False, False, PDP_URL, "partial", PARTIAL_MSG),
        (True, True, False, False, PDP_URL, "partial", PARTIAL_MSG),
        (False, False, True, False, PDP_URL, "partial", PARTIAL_MSG),
        (True, False, True, False, PDP_URL, "partial", PARTIAL_MSG),
        (False, True, True, False, PDP_URL, "partial", PARTIAL_MSG),
        (True, True, True, False, PDP_URL, "partial", PARTIAL_MSG),
        (False, False, False, True, PDP_URL, "partial", PARTIAL_MSG),
        (True, False, False, True, PDP_URL, "partial", PARTIAL_MSG),
        (False, True, False, True, PDP_URL, "partial", PARTIAL_MSG),
        (True, True, False, True, PDP_URL, "partial", PARTIAL_MSG),
        (False, False, True, True, PDP_URL, "partial", PARTIAL_MSG),
        (True, False, True, True, PDP_URL, "partial", PARTIAL_MSG),
        (False, True, True, True, PDP_URL, "partial", PARTIAL_MSG),
        (True, True, True, True, PDP_URL, "completed", None),  # All success
    ]

    for home_d, home_m, pdp_d, pdp_m, pdp_url, exp_status, exp_summary_substr in test_cases:
        status, summary = compute_session_status(home_d, home_m, pdp_d, pdp_m, pdp_url)
        assert status == exp_status, (
            f"Failed for {(home_d, home_m, pdp_d, pdp_m, pdp_url)}: "
            f"expected {exp_status}, got {status}"
        )
        if exp_summary_substr:
            assert exp_summary_substr in (summary or ""), (
                f"Expected summary to contain '{exp_summary_substr}', got '{summary}'"
            )
        else:
            assert summary is None, f"Expected None summary for completed, got '{summary}'"


def test_compute_session_status_completed_only_with_all_success():
    """Status is 'completed' only when all 4 viewports succeed AND pdp_url present."""
    # All success with PDP
    status, summary = compute_session_status(True, True, True, True, "https://example.com/p/1")
    assert status == "completed"
    assert summary is None

    # All success but no PDP -> partial
    status2, summary2 = compute_session_status(True, True, True, True, None)
    assert status2 == "partial"
    assert summary2 == "PDP not found"

    # PDP present but one failure -> partial
    status3, summary3 = compute_session_status(True, True, True, False, "https://example.com/p/1")
    assert status3 == "partial"
    assert summary3 == "One or more viewports failed"


def test_compute_session_status_failed_only_when_all_fail():
    """Status is 'failed' only when all viewports fail or homepage fails with no PDP."""
    # All fail with PDP
    status, summary = compute_session_status(False, False, False, False, "https://example.com/p/1")
    assert status == "failed"
    assert summary == "All viewports failed"

    # All fail without PDP
    status2, summary2 = compute_session_status(False, False, False, False, None)
    assert status2 == "failed"
    assert summary2 == "All viewports failed"

    # Any success prevents failed status (becomes partial)
    status3, summary3 = compute_session_status(True, False, False, False, "https://example.com/p/1")
    assert status3 == "partial"


def test_compute_session_status_partial_middle_ground():
    """Status is 'partial' for all cases between completed and failed."""
    # PDP not found but homepage succeeds
    assert compute_session_status(True, True, False, False, None)[0] == "partial"

    # PDP found but some viewports fail
    assert compute_session_status(True, True, True, False, PDP_URL)[0] == "partial"
    assert compute_session_status(True, False, True, True, PDP_URL)[0] == "partial"
    assert compute_session_status(False, True, True, True, PDP_URL)[0] == "partial"


# --- Low-confidence rollup edge cases ---


def test_session_low_confidence_from_pages_multiple_pages_with_reasons():
    """Multiple pages with reasons still result in True."""
    pages = [
        {"low_confidence_reasons": ["missing_h1"]},
        {"low_confidence_reasons": ["screenshot_failed"]},
        {"low_confidence_reasons": ["text_too_short_50"]},
    ]
    assert session_low_confidence_from_pages(pages) is True


def test_session_low_confidence_from_pages_mixed_empty_and_reasons():
    """Mix of empty and non-empty reasons results in True."""
    pages = [
        {"low_confidence_reasons": []},
        {"low_confidence_reasons": []},
        {"low_confidence_reasons": ["missing_price"]},
        {"low_confidence_reasons": []},
    ]
    assert session_low_confidence_from_pages(pages) is True


def test_session_low_confidence_from_pages_empty_list_vs_missing_key():
    """Empty list and missing key both treated as no reasons."""
    pages_empty = [{"low_confidence_reasons": []}]
    pages_missing = [{"other_field": "value"}]

    assert session_low_confidence_from_pages(pages_empty) is False
    assert session_low_confidence_from_pages(pages_missing) is False


# --- Status determinism ---


def test_compute_session_status_deterministic():
    """Same inputs produce identical outputs across multiple calls."""
    inputs = (True, True, True, False, "https://example.com/p/1")

    results = [compute_session_status(*inputs) for _ in range(10)]

    # All results identical
    for result in results:
        assert result == results[0]

    assert results[0] == ("partial", "One or more viewports failed")


def test_session_low_confidence_rollup_deterministic():
    """Rollup produces consistent results across multiple calls."""
    pages = [
        {"low_confidence_reasons": []},
        {"low_confidence_reasons": ["missing_h1"]},
    ]

    results = [session_low_confidence_from_pages(pages) for _ in range(10)]

    # All results identical
    for result in results:
        assert result == results[0]

    assert results[0] is True
