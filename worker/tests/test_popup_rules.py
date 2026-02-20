"""
Unit tests for popup rules: selector order, overlay detection, safe/risky text heuristics.

Per TECH_SPEC_V1.1.md §5 Popup Handling Policy v1.6.
Covers: deterministic selector order, overlay-first ordering, safe-click keywords,
no unsafe CTAs (buy/checkout/allow notifications). No network or Playwright required.
"""

from __future__ import annotations

import pytest

from worker.crawl.constants import (
    MAX_DISMISSALS_PER_PASS,
    POPUP_CATEGORY_ORDER,
    POPUP_CATEGORY_ORDER_OVERLAY_FIRST,
    POPUP_SELECTORS_COOKIE,
    POPUP_SELECTORS_MODAL,
    RISKY_CTA_KEYWORDS,
    SAFE_DISMISS_KEYWORDS,
)
from worker.crawl.popup_rules import (
    POPUP_SELECTORS_BY_CATEGORY,
    get_popup_selectors_in_order,
    is_risky_cta_text,
    is_safe_dismiss_text,
)

# --- Deterministic behavior (selector order) ---


def test_get_popup_selectors_in_order_deterministic():
    """Same arguments produce the same selector list every time."""
    a = get_popup_selectors_in_order(overlay_first=False)
    b = get_popup_selectors_in_order(overlay_first=False)
    assert a == b
    c = get_popup_selectors_in_order(overlay_first=True)
    d = get_popup_selectors_in_order(overlay_first=True)
    assert c == d


def test_get_popup_selectors_in_order_non_empty():
    """Selector lists are non-empty and contain strings."""
    default_order = get_popup_selectors_in_order(overlay_first=False)
    overlay_order = get_popup_selectors_in_order(overlay_first=True)
    assert len(default_order) > 0
    assert len(overlay_order) > 0
    assert all(isinstance(s, str) and len(s) > 0 for s in default_order)
    assert all(isinstance(s, str) and len(s) > 0 for s in overlay_order)


def test_default_order_puts_cookie_first():
    """Without overlay_first, first category is cookie; first selectors match cookie set."""
    selectors = get_popup_selectors_in_order(overlay_first=False)
    cookie_set = set(POPUP_SELECTORS_COOKIE)
    assert selectors[0] in cookie_set
    assert selectors[: len(POPUP_SELECTORS_COOKIE)] == list(POPUP_SELECTORS_COOKIE)


def test_overlay_first_puts_modal_first():
    """With overlay_first=True, first category is modal; first selectors match modal set."""
    selectors = get_popup_selectors_in_order(overlay_first=True)
    modal_set = set(POPUP_SELECTORS_MODAL)
    assert selectors[0] in modal_set
    assert selectors[: len(POPUP_SELECTORS_MODAL)] == list(POPUP_SELECTORS_MODAL)


def test_overlay_detection_order():
    """Overlay-first order is modal → cookie → newsletter → age_gate → geo."""
    order = POPUP_CATEGORY_ORDER_OVERLAY_FIRST
    assert order == ("modal", "cookie", "newsletter", "age_gate", "geo")
    selectors = get_popup_selectors_in_order(overlay_first=True)
    # First block = modal
    n_modal = len(POPUP_SELECTORS_BY_CATEGORY["modal"])
    assert selectors[:n_modal] == list(POPUP_SELECTORS_BY_CATEGORY["modal"])


def test_default_category_order():
    """Default category order is cookie → newsletter → modal → age_gate → geo."""
    assert POPUP_CATEGORY_ORDER == ("cookie", "newsletter", "modal", "age_gate", "geo")


# --- Safe-click ordering and no unsafe CTAs ---


@pytest.mark.parametrize(
    "text",
    [
        "Accept",
        "Accept All",
        "I Accept",
        "close",
        "Close",
        "No thanks",
        "Maybe later",
        "OK",
        "ok",
        "  accept  ",
        "allow all",
        "dismiss",
        "agree",
        "Got it",
        "Continue",
        "Në rregull",
        "×",
        "✕",
    ],
)
def test_is_safe_dismiss_text_accepts_dismiss_keywords(text: str):
    """Safe-dismiss keywords and common variants are accepted."""
    assert is_safe_dismiss_text(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Learn more",
        "Buy",
        "Buy now",
        "Subscribe",
        "",
        "   ",
        "random",
    ],
)
def test_is_safe_dismiss_text_rejects_non_dismiss(text: str):
    """Non-dismiss and empty text are rejected."""
    assert is_safe_dismiss_text(text) is False


def test_is_safe_dismiss_text_rejects_none():
    """None is rejected."""
    assert is_safe_dismiss_text(None) is False


@pytest.mark.parametrize(
    "text",
    [
        "Buy now",
        "buy",
        "Checkout",
        "checkout",
        "Allow notification",
        "enable notification",
        "Subscribe",
        "subscribe to our newsletter",
    ],
)
def test_is_risky_cta_text_rejects_unsafe(text: str):
    """Risky CTA keywords (buy, checkout, allow notifications, subscribe) are rejected."""
    assert is_risky_cta_text(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Accept",
        "Close",
        "No thanks",
        "OK",
        "accept all cookies",
    ],
)
def test_is_risky_cta_text_accepts_safe(text: str):
    """Safe-dismiss text is not classified as risky."""
    assert is_risky_cta_text(text) is False


def test_is_risky_cta_text_rejects_none():
    """None is not risky (no click)."""
    assert is_risky_cta_text(None) is False


def test_no_unsafe_ctas_safe_keywords_not_risky():
    """Every safe-dismiss keyword is not risky (no overlap with risky CTAs)."""
    for kw in SAFE_DISMISS_KEYWORDS:
        assert is_risky_cta_text(kw) is False, f"Safe keyword '{kw}' must not be risky"


def test_risky_keywords_are_not_safe_dismiss():
    """Risky CTA keywords are not accepted as safe-dismiss (no accidental click)."""
    for kw in RISKY_CTA_KEYWORDS:
        assert is_safe_dismiss_text(kw) is False, f"Risky keyword '{kw}' must not be safe-dismiss"


# --- Overlay detection inputs/outputs ---


def test_popup_selectors_by_category_has_all_categories():
    """All five categories exist and have non-empty selector tuples."""
    expected = {"cookie", "newsletter", "modal", "age_gate", "geo"}
    assert set(POPUP_SELECTORS_BY_CATEGORY.keys()) == expected
    for cat, selectors in POPUP_SELECTORS_BY_CATEGORY.items():
        assert isinstance(selectors, tuple), f"{cat} should be tuple"
        assert len(selectors) > 0, f"{cat} should be non-empty"
        assert all(isinstance(s, str) and s for s in selectors), (
            f"{cat} selectors must be non-empty strings"
        )


def test_overlay_first_and_default_same_total_selectors():
    """Overlay-first and default order yield the same total selector count."""
    default = get_popup_selectors_in_order(overlay_first=False)
    overlay = get_popup_selectors_in_order(overlay_first=True)
    assert len(default) == len(overlay)
    assert set(default) == set(overlay)


def test_max_dismissals_per_pass_positive():
    """MAX_DISMISSALS_PER_PASS is a positive bounded constant."""
    assert MAX_DISMISSALS_PER_PASS >= 1
    assert isinstance(MAX_DISMISSALS_PER_PASS, int)
