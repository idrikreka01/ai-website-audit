"""
Unit tests for PDP low-confidence evaluation rules (evaluate_low_confidence_pdp).
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
