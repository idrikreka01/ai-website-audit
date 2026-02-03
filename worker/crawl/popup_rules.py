"""
Popup handling rules: selector order, safe/risky text heuristics, overlay removal.

Per TECH_SPEC_V1.1.md §5 Popup Handling Policy v1.6.
Centralizes selector lists and keyword heuristics; no risky CTAs (buy/checkout/allow notifications).
Includes JS for overlay DOM removal and scroll unlock.
"""

from __future__ import annotations

from worker.crawl.constants import (
    POPUP_CATEGORY_ORDER,
    POPUP_CATEGORY_ORDER_OVERLAY_FIRST,
    POPUP_SELECTORS_AGE_GATE,
    POPUP_SELECTORS_APP_DOWNLOAD,
    POPUP_SELECTORS_COOKIE,
    POPUP_SELECTORS_GEO,
    POPUP_SELECTORS_MODAL,
    POPUP_SELECTORS_NEWSLETTER,
    RISKY_CTA_KEYWORDS,
    SAFE_DISMISS_KEYWORDS,
)

OVERLAY_REMOVE_JS = """
(function() {
  const selectors = [
    '[role="dialog"]', '[aria-modal="true"]',
    '.modal', '.popup', '.modal-backdrop', '.popup-overlay',
    '.cookie-banner', '[class*="cookie-banner"]',
    '[class*="CookieBanner"]', '[id*="cookie"]', '[id*="Cookie"]',
    '.newsletter-popup', '[class*="newsletter"]', '[class*="Newsletter"]',
    '.discount-popup', '[class*="discount"]', '[class*="Discount"]',
    '.promo-popup', '[class*="promo-popup"]', '[class*="welcome"]',
    '.overlay', '[class*="overlay"]', '.gdpr-banner', '.consent-banner',
    '[class*="app-download"]', '[class*="appDownload"]', '[id*="app-download"]',
    '[class*="onetrust"]', '#onetrust-consent-sdk', '.cc-window', '.cc_banner'
  ];
  const byZ = [];
  document.querySelectorAll('*').forEach(el => {
    const s = window.getComputedStyle(el);
    if (s.position === 'fixed' && parseInt(s.zIndex || '0', 10) > 100) {
      const rect = el.getBoundingClientRect();
      if (rect.width > 100 && rect.height > 100) byZ.push(el);
    }
  });
  const seen = new Set();
  selectors.forEach(sel => {
    try {
      document.querySelectorAll(sel).forEach(el => {
        if (!seen.has(el)) { seen.add(el); el.remove(); }
      });
    } catch (_) {}
  });
  byZ.forEach(el => { if (!seen.has(el)) { seen.add(el); el.remove(); } });
})();
"""

SCROLL_UNLOCK_JS = """
document.body.style.overflow = 'auto';
document.documentElement.style.overflow = 'auto';
document.body.style.position = '';
document.documentElement.style.position = '';
"""

CLOSE_BUTTON_XPATH = [
    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree')]",
    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'close')]",
    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'dismiss')]",
    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'no thanks')]",
    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'continue')]",
    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'got it')]",
    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ok')]",
    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'maybe later')]",
    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'vazhdo')]",
    "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
    "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree')]",
    "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'close')]",
    "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'dismiss')]",
    "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'no thanks')]",
    "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'vazhdo')]",
    "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept all')]",
    "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept cookies')]",
    "//*[contains(., '×') or contains(., '✕')]",
]

CLOSE_CSS = [
    "button[aria-label='Close']",
    "button[aria-label='close']",
    "[aria-label*='close' i]",
    "[aria-label*='dismiss' i]",
    "[role='dialog'] button",
    "[aria-modal='true'] button",
    ".modal button",
    ".popup button",
    ".modal-close",
    ".popup-close",
    ".close-button",
    ".close-btn",
    "[class*='cookie'] button",
    "[class*='Cookie'] button",
    "[class*='banner'] button",
    "[class*='newsletter'] button",
    "[class*='discount'] button",
    "[class*='promo'] button",
    "[class*='overlay'] button",
    "[id*='cookie'] button",
    "[id*='Cookie'] button",
    "[id*='popup'] button",
    "[id*='Popup'] button",
    "[data-dismiss='modal']",
    "[data-close]",
    "[data-testid*='close']",
    "[data-testid*='dismiss']",
]

# Map category name -> tuple of selectors (read-only)
POPUP_SELECTORS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "cookie": POPUP_SELECTORS_COOKIE,
    "newsletter": POPUP_SELECTORS_NEWSLETTER,
    "modal": POPUP_SELECTORS_MODAL,
    "app_download": POPUP_SELECTORS_APP_DOWNLOAD,
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
