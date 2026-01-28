"""
Unit tests for low-confidence evaluation rules.
"""

from __future__ import annotations

import pytest

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
