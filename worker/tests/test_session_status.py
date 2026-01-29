"""
Unit tests for session status computation (compute_session_status, PDP-not-found).
"""

from __future__ import annotations

from worker.session_status import compute_session_status, session_low_confidence_from_pages


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
