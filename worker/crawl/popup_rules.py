"""
Popup handling rules: selector order and safe/risky text heuristics.

Per TECH_SPEC_V1.1.md §5 Popup Handling Policy v1.6.
Centralizes selector lists and keyword heuristics; no risky CTAs (buy/checkout/allow notifications).
"""

from __future__ import annotations

from worker.crawl.constants import (
    POPUP_CATEGORY_ORDER,
    POPUP_CATEGORY_ORDER_OVERLAY_FIRST,
    POPUP_SELECTORS_AGE_GATE,
    POPUP_SELECTORS_COOKIE,
    POPUP_SELECTORS_GEO,
    POPUP_SELECTORS_MODAL,
    POPUP_SELECTORS_NEWSLETTER,
    RISKY_CTA_KEYWORDS,
    SAFE_DISMISS_KEYWORDS,
)

# Map category name -> tuple of selectors (read-only)
POPUP_SELECTORS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "cookie": POPUP_SELECTORS_COOKIE,
    "newsletter": POPUP_SELECTORS_NEWSLETTER,
    "modal": POPUP_SELECTORS_MODAL,
    "age_gate": POPUP_SELECTORS_AGE_GATE,
    "geo": POPUP_SELECTORS_GEO,
}


def get_popup_selectors_in_order(*, overlay_first: bool = False) -> list[str]:
    """
    Return popup selectors in deterministic category order.

    If overlay_first=True, prioritizes overlay (dialog/banner) selectors first
    (TECH_SPEC §5 detection layers). Otherwise: cookie → newsletter → modal → age_gate → geo.
    Used for one pass of popup dismissal (TECH_SPEC two-pass flow).
    """
    order = POPUP_CATEGORY_ORDER_OVERLAY_FIRST if overlay_first else POPUP_CATEGORY_ORDER
    out: list[str] = []
    for category in order:
        out.extend(POPUP_SELECTORS_BY_CATEGORY.get(category, ()))
    return out


def _normalize_text(text: str | None) -> str:
    """Normalize for keyword matching: lowercase, collapse whitespace, strip."""
    if not text:
        return ""
    return " ".join(str(text).lower().split()).strip()


def is_safe_dismiss_text(text: str | None) -> bool:
    """
    True if normalized text matches a safe dismiss keyword (accept, close, etc.).

    Deterministic and minimal; used to allow only dismiss semantics when
    filtering by button/link text.
    """
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return any(kw in normalized or normalized in kw for kw in SAFE_DISMISS_KEYWORDS)


def is_risky_cta_text(text: str | None) -> bool:
    """
    True if normalized text contains a risky CTA (buy, checkout, allow notifications).

    Never click such elements. Deterministic and minimal.
    """
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return any(kw in normalized for kw in RISKY_CTA_KEYWORDS)
