"""
Unit tests for low-confidence evaluation rules (homepage).

Asserts exact reason strings and threshold behavior per TECH_SPEC.
No logic change to low_confidence.py.
"""

from __future__ import annotations

from worker.low_confidence import evaluate_low_confidence


def test_low_confidence_missing_h1():
    """Test that missing H1 triggers low confidence."""
    low_confidence, reasons = evaluate_low_confidence(
        has_h1=False,
        has_primary_cta=True,
        visible_text_length=500,
        screenshot_failed=False,
        screenshot_blank=False,
    )

    assert low_confidence is True
    assert "missing_h1" in reasons


def test_low_confidence_missing_cta():
    """Test that missing primary CTA triggers low confidence."""
    low_confidence, reasons = evaluate_low_confidence(
        has_h1=True,
        has_primary_cta=False,
        visible_text_length=500,
        screenshot_failed=False,
        screenshot_blank=False,
    )

    assert low_confidence is True
    assert "missing_primary_cta" in reasons


def test_low_confidence_text_too_short():
    """Test that short text triggers low confidence."""
    low_confidence, reasons = evaluate_low_confidence(
        has_h1=True,
        has_primary_cta=True,
        visible_text_length=50,  # Below 100 threshold
        screenshot_failed=False,
        screenshot_blank=False,
    )

    assert low_confidence is True
    assert any("text_too_short" in reason for reason in reasons)


def test_low_confidence_screenshot_failed():
    """Test that failed screenshot triggers low confidence."""
    low_confidence, reasons = evaluate_low_confidence(
        has_h1=True,
        has_primary_cta=True,
        visible_text_length=500,
        screenshot_failed=True,
        screenshot_blank=False,
    )

    assert low_confidence is True
    assert "screenshot_failed" in reasons


def test_low_confidence_screenshot_blank():
    """Test that blank screenshot triggers low confidence."""
    low_confidence, reasons = evaluate_low_confidence(
        has_h1=True,
        has_primary_cta=True,
        visible_text_length=500,
        screenshot_failed=False,
        screenshot_blank=True,
    )

    assert low_confidence is True
    assert "screenshot_blank" in reasons


def test_low_confidence_multiple_reasons():
    """Test that multiple issues accumulate reasons."""
    low_confidence, reasons = evaluate_low_confidence(
        has_h1=False,
        has_primary_cta=False,
        visible_text_length=50,
        screenshot_failed=True,
        screenshot_blank=False,
    )

    assert low_confidence is True
    assert len(reasons) >= 3
    assert "missing_h1" in reasons
    assert "missing_primary_cta" in reasons
    assert "screenshot_failed" in reasons


def test_high_confidence_all_ok():
    """Test that all criteria met results in high confidence."""
    low_confidence, reasons = evaluate_low_confidence(
        has_h1=True,
        has_primary_cta=True,
        visible_text_length=500,
        screenshot_failed=False,
        screenshot_blank=False,
    )

    assert low_confidence is False
    assert len(reasons) == 0


# --- Exact reason strings and threshold (spec alignment) ---


def test_low_confidence_exact_reason_strings():
    """Reason strings match spec exactly: missing_h1, missing_primary_cta, etc."""
    _, reasons = evaluate_low_confidence(
        has_h1=False,
        has_primary_cta=False,
        visible_text_length=50,
        screenshot_failed=True,
        screenshot_blank=True,
    )
    assert "missing_h1" in reasons
    assert "missing_primary_cta" in reasons
    assert "screenshot_failed" in reasons
    assert "screenshot_blank" in reasons
    # text_too_short format: text_too_short_{visible_text_length}
    text_reasons = [r for r in reasons if r.startswith("text_too_short_")]
    assert len(text_reasons) == 1
    assert text_reasons[0] == "text_too_short_50"


def test_low_confidence_text_threshold_boundary():
    """Text length threshold 100: below triggers, at or above does not."""
    _, reasons_below = evaluate_low_confidence(
        has_h1=True,
        has_primary_cta=True,
        visible_text_length=99,
        screenshot_failed=False,
        screenshot_blank=False,
    )
    assert any(r.startswith("text_too_short_") for r in reasons_below)
    assert any(r == "text_too_short_99" for r in reasons_below)

    _, reasons_at = evaluate_low_confidence(
        has_h1=True,
        has_primary_cta=True,
        visible_text_length=100,
        screenshot_failed=False,
        screenshot_blank=False,
    )
    assert not any(r.startswith("text_too_short_") for r in reasons_at)

    _, reasons_above = evaluate_low_confidence(
        has_h1=True,
        has_primary_cta=True,
        visible_text_length=101,
        screenshot_failed=False,
        screenshot_blank=False,
    )
    assert not any(r.startswith("text_too_short_") for r in reasons_above)


def test_low_confidence_no_extra_reasons():
    """Only spec-defined reasons appear; no additional keys."""
    allowed = {"missing_h1", "missing_primary_cta", "screenshot_failed", "screenshot_blank"}
    _, reasons = evaluate_low_confidence(
        has_h1=False,
        has_primary_cta=False,
        visible_text_length=50,
        screenshot_failed=True,
        screenshot_blank=True,
    )
    for r in reasons:
        if r.startswith("text_too_short_"):
            continue
        assert r in allowed, f"Unexpected reason: {r}"
