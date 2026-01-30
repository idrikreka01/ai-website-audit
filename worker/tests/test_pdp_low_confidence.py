"""
Unit tests for PDP low-confidence evaluation rules (evaluate_low_confidence_pdp).

Asserts exact reason strings and threshold behavior per TECH_SPEC.
No logic change to low_confidence.py.
"""

from __future__ import annotations

from worker.low_confidence import MIN_TEXT_LENGTH_PDP, evaluate_low_confidence_pdp


def test_pdp_low_confidence_missing_h1():
    low_confidence, reasons = evaluate_low_confidence_pdp(
        has_h1=False,
        has_primary_cta=True,
        has_price=True,
        has_add_to_cart=True,
        visible_text_length=500,
        screenshot_failed=False,
        screenshot_blank=False,
    )
    assert low_confidence is True
    assert "missing_h1" in reasons


def test_pdp_low_confidence_missing_price():
    low_confidence, reasons = evaluate_low_confidence_pdp(
        has_h1=True,
        has_primary_cta=True,
        has_price=False,
        has_add_to_cart=True,
        visible_text_length=500,
        screenshot_failed=False,
        screenshot_blank=False,
    )
    assert low_confidence is True
    assert "missing_price" in reasons


def test_pdp_low_confidence_missing_add_to_cart():
    low_confidence, reasons = evaluate_low_confidence_pdp(
        has_h1=True,
        has_primary_cta=True,
        has_price=True,
        has_add_to_cart=False,
        visible_text_length=500,
        screenshot_failed=False,
        screenshot_blank=False,
    )
    assert low_confidence is True
    assert "missing_add_to_cart" in reasons


def test_pdp_low_confidence_text_too_short():
    low_confidence, reasons = evaluate_low_confidence_pdp(
        has_h1=True,
        has_primary_cta=True,
        has_price=True,
        has_add_to_cart=True,
        visible_text_length=50,
        screenshot_failed=False,
        screenshot_blank=False,
    )
    assert low_confidence is True
    assert any("text_too_short" in r for r in reasons)


def test_pdp_low_confidence_screenshot_failed():
    low_confidence, reasons = evaluate_low_confidence_pdp(
        has_h1=True,
        has_primary_cta=True,
        has_price=True,
        has_add_to_cart=True,
        visible_text_length=500,
        screenshot_failed=True,
        screenshot_blank=False,
    )
    assert low_confidence is True
    assert "screenshot_failed" in reasons


def test_pdp_high_confidence_all_ok():
    low_confidence, reasons = evaluate_low_confidence_pdp(
        has_h1=True,
        has_primary_cta=True,
        has_price=True,
        has_add_to_cart=True,
        visible_text_length=500,
        screenshot_failed=False,
        screenshot_blank=False,
    )
    assert low_confidence is False
    assert len(reasons) == 0


def test_pdp_min_text_length_constant():
    assert MIN_TEXT_LENGTH_PDP == 100


# --- Exact reason strings and threshold (spec alignment) ---


def test_pdp_low_confidence_exact_reason_strings():
    """PDP reason strings match spec: missing_h1, missing_price, missing_add_to_cart, etc."""
    _, reasons = evaluate_low_confidence_pdp(
        has_h1=False,
        has_primary_cta=False,
        has_price=False,
        has_add_to_cart=False,
        visible_text_length=50,
        screenshot_failed=True,
        screenshot_blank=True,
    )
    assert "missing_h1" in reasons
    assert "missing_primary_cta" in reasons
    assert "missing_price" in reasons
    assert "missing_add_to_cart" in reasons
    assert "screenshot_failed" in reasons
    assert "screenshot_blank" in reasons
    text_reasons = [r for r in reasons if r.startswith("text_too_short_")]
    assert len(text_reasons) == 1
    assert text_reasons[0] == "text_too_short_50"


def test_pdp_low_confidence_text_threshold_boundary():
    """PDP text threshold MIN_TEXT_LENGTH_PDP (100): below triggers, at or above does not."""
    _, reasons_below = evaluate_low_confidence_pdp(
        has_h1=True,
        has_primary_cta=True,
        has_price=True,
        has_add_to_cart=True,
        visible_text_length=99,
        screenshot_failed=False,
        screenshot_blank=False,
    )
    assert any(r == "text_too_short_99" for r in reasons_below)

    _, reasons_at = evaluate_low_confidence_pdp(
        has_h1=True,
        has_primary_cta=True,
        has_price=True,
        has_add_to_cart=True,
        visible_text_length=100,
        screenshot_failed=False,
        screenshot_blank=False,
    )
    assert not any(r.startswith("text_too_short_") for r in reasons_at)

    _, reasons_above = evaluate_low_confidence_pdp(
        has_h1=True,
        has_primary_cta=True,
        has_price=True,
        has_add_to_cart=True,
        visible_text_length=101,
        screenshot_failed=False,
        screenshot_blank=False,
    )
    assert not any(r.startswith("text_too_short_") for r in reasons_above)


def test_pdp_low_confidence_no_extra_reasons():
    """Only spec-defined PDP reasons appear."""
    allowed = {
        "missing_h1",
        "missing_primary_cta",
        "missing_price",
        "missing_add_to_cart",
        "screenshot_failed",
        "screenshot_blank",
    }
    _, reasons = evaluate_low_confidence_pdp(
        has_h1=False,
        has_primary_cta=False,
        has_price=False,
        has_add_to_cart=False,
        visible_text_length=50,
        screenshot_failed=True,
        screenshot_blank=True,
    )
    for r in reasons:
        if r.startswith("text_too_short_"):
            continue
        assert r in allowed, f"Unexpected reason: {r}"
