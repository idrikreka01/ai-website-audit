"""
Low-confidence detection rules per TECH_SPEC_V1.md.

These are pure functions that evaluate whether a page should be marked
as low_confidence based on extracted features.
"""

from __future__ import annotations

from typing import Literal

Viewport = Literal["desktop", "mobile"]


def evaluate_low_confidence(
    *,
    has_h1: bool,
    has_primary_cta: bool,
    visible_text_length: int,
    screenshot_failed: bool,
    screenshot_blank: bool,
) -> tuple[bool, list[str]]:
    """
    Evaluate low-confidence flags per TECH_SPEC rules.

    Returns (low_confidence: bool, reasons: list[str]).
    """
    reasons = []

    if not has_h1:
        reasons.append("missing_h1")

    if not has_primary_cta:
        reasons.append("missing_primary_cta")

    # Text length threshold (minimum 100 characters for homepage)
    min_text_length = 100
    if visible_text_length < min_text_length:
        reasons.append(f"text_too_short_{visible_text_length}")

    if screenshot_failed:
        reasons.append("screenshot_failed")

    if screenshot_blank:
        reasons.append("screenshot_blank")

    return len(reasons) > 0, reasons


# PDP-specific: same text threshold (100 chars), plus price/add-to-cart
MIN_TEXT_LENGTH_PDP = 100


def evaluate_low_confidence_pdp(
    *,
    has_h1: bool,
    has_primary_cta: bool,
    has_price: bool,
    has_add_to_cart: bool,
    visible_text_length: int,
    screenshot_failed: bool,
    screenshot_blank: bool,
) -> tuple[bool, list[str]]:
    """
    Evaluate low-confidence for a PDP page per TECH_SPEC.

    PDP rules: H1 missing, primary CTA missing, missing price OR add-to-cart,
    visible text below threshold, screenshot failed/blank.

    Returns (low_confidence: bool, reasons: list[str]).
    """
    reasons = []

    if not has_h1:
        reasons.append("missing_h1")

    if not has_primary_cta:
        reasons.append("missing_primary_cta")

    if not has_price:
        reasons.append("missing_price")

    if not has_add_to_cart:
        reasons.append("missing_add_to_cart")

    if visible_text_length < MIN_TEXT_LENGTH_PDP:
        reasons.append(f"text_too_short_{visible_text_length}")

    if screenshot_failed:
        reasons.append("screenshot_failed")

    if screenshot_blank:
        reasons.append("screenshot_blank")

    return len(reasons) > 0, reasons
