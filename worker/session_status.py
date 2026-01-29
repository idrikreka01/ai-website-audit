"""
Session status computation from per-viewport results (pure functions).

Computes final_status, error_summary, and session-level low_confidence rollup.
Per TECH_SPEC: if PDP not found but homepage succeeds → partial.
"""

from __future__ import annotations


def compute_session_status(
    home_desktop_success: bool,
    home_mobile_success: bool,
    pdp_desktop_success: bool,
    pdp_mobile_success: bool,
    pdp_url: str | None,
) -> tuple[str, str | None]:
    """
    Compute final session status and error_summary from viewport results.

    Per TECH_SPEC: If PDP fails but homepage succeeds → partial. When pdp_url
    is None (PDP not found), session is partial if homepage succeeded else failed.

    Args:
        home_desktop_success: Homepage desktop crawl succeeded.
        home_mobile_success: Homepage mobile crawl succeeded.
        pdp_desktop_success: PDP desktop crawl succeeded (only relevant if pdp_url).
        pdp_mobile_success: PDP mobile crawl succeeded (only relevant if pdp_url).
        pdp_url: Selected PDP URL, or None if no PDP.

    Returns:
        (final_status, error_summary)
        final_status: "completed" | "partial" | "failed"
        error_summary: User-safe message, or None when completed.
    """
    if pdp_url is None:
        # PDP not found: partial if homepage succeeded, failed otherwise
        home_ok = home_desktop_success and home_mobile_success
        if home_ok:
            return "partial", "PDP not found"
        return "failed", "All viewports failed"

    total_pages = 4
    success_count = sum(
        [home_desktop_success, home_mobile_success, pdp_desktop_success, pdp_mobile_success]
    )

    if success_count == total_pages:
        return "completed", None
    if success_count > 0:
        return "partial", "One or more viewports failed"
    return "failed", "All viewports failed"


def session_low_confidence_from_pages(pages: list[dict]) -> bool:
    """
    Return True if any page has non-empty low_confidence_reasons.

    Args:
        pages: List of page dicts from get_pages_by_session_id.

    Returns:
        True if session should be marked low_confidence.
    """
    for page in pages:
        reasons = page.get("low_confidence_reasons", [])
        if reasons and len(reasons) > 0:
            return True
    return False
