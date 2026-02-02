"""
Crawl constants: viewport configs, timeouts, PDP patterns, excluded segments.

Per TECH_SPEC_V1.md; no behavior change.
"""

from __future__ import annotations

from typing import Literal

Viewport = Literal["desktop", "mobile"]

# Viewport configurations
VIEWPORT_CONFIGS = {
    "desktop": {"width": 1920, "height": 1080},
    "mobile": {"width": 375, "height": 667},
}

# Timeout constants (in milliseconds)
NETWORK_IDLE_TIMEOUT = 800  # Network idle window
DOM_STABILITY_TIMEOUT = 1000  # DOM stability window
MINIMUM_WAIT_AFTER_LOAD = 500  # Minimum wait after load
CONSENT_POSITIONING_DELAY_MS = 800  # Wait for consent banner to position (e.g. bottom) before dismiss
HARD_TIMEOUT_MS = 30000  # Hard timeout cap per page
SCROLL_WAIT = 500  # Wait after each scroll

# URL path patterns for PDP candidates (case-insensitive); match path segment or full path
PDP_PATH_PATTERNS = [
    r"/product(?:s)?/",  # /product/, /products/
    r"/p/",
    r"/item(?:s)?/",
    r"/collections/[^/]+/products/",  # Shopify
    r"/products/",  # Shopify
    r"/shop/",  # common
]
# Paths to exclude (account, cart, checkout, logout)
EXCLUDED_PATH_SEGMENTS = {"account", "cart", "checkout", "logout", "login", "signin", "signout"}

# Max PDP candidates to validate (deterministic cap)
MAX_PDP_CANDIDATES = 20

# Container element selectors (product-like boxes). Links inside are candidates when
# the container has at least PRODUCT_CONTAINER_MIN_SIGNALS of: price, title, image, add-to-cart.
PRODUCT_CONTAINER_SELECTORS = [
    ".product",
    "[class*='product-box']",
    "[class*='product-card']",
    "[class*='product-item']",
    ".card",
    "[class*='theProduct']",
    "[data-product-id]",
    "[data-product]",
]

# Legacy: broad "container a[href]" selectors for pattern-free candidate collection.
# Context pass uses PRODUCT_CONTAINER_SELECTORS + 2-of-4 signal check instead.
PRODUCT_LIKE_CONTAINER_SELECTORS = [
    ".product a[href]",
    "[class*='product-box'] a[href]",
    "[class*='product-card'] a[href]",
    "[class*='product-item'] a[href]",
    ".card a[href]",
    "[class*='theProduct'] a[href]",
    "[data-product-id] a[href]",
    "[data-product] a[href]",
]

# Minimum signals (2-of-4) required inside a product-like container to accept its links.
PRODUCT_CONTAINER_MIN_SIGNALS = 2

# Selectors for container signal detection (price, title, image, add-to-cart).
# Used when evaluating product-like containers; at least MIN_SIGNALS must match.
PRODUCT_CONTAINER_PRICE_SELECTORS = [
    "[class*='price'], [data-price], [itemprop='price']",
]
PRODUCT_CONTAINER_TITLE_SELECTORS = [
    "h1, h2, h3, [class*='product-name'], [class*='product_title'], [itemprop='name']",
]
PRODUCT_CONTAINER_IMAGE_SELECTOR = "img"
PRODUCT_CONTAINER_ADD_TO_CART_SELECTORS = [
    "[class*='add-to-cart'], [class*='addToCart'], [name='add-to-cart']",
    "button:has-text('Add to Cart'), button:has-text('Add to Bag'), button:has-text('Buy Now')",
    "[class*='cart']",
]

# --- Popup handling (TECH_SPEC_V1.1.md §5 Popup Handling Policy v1.6) ---
# Selectors are categorized; only dismiss semantics (no buy/checkout/allow notifications).
# Order of categories is applied in popup_rules.get_popup_selectors_in_order().

# Cookie consent / GDPR banners (broad selector list; safe-click filtering applies)
COOKIE_CONSENT_SELECTORS = [
    'button:has-text("cookies")',
    'button:has-text("Prano të gjitha cookies")',
    'button:has-text("Ruaj")',
    'button:has-text("Prano")',
    'button:has-text("Accept")',
    'button:has-text("Accept All")',
    'button:has-text("Accept all")',
    'button:has-text("Select all")',
    'button:has-text("Select All")',
    'button:has-text("Accept All Cookies")',
    'button:has-text("I Accept")',
    'button:has-text("I Agree")',
    'button:has-text("Agree")',
    'button:has-text("Agree All")',
    'button:has-text("Allow All")',
    'button:has-text("Allow all")',
    'button:has-text("Allow essential")',
    'button:has-text("Got it")',
    'button:has-text("Continue")',
    'button:has-text("Close")',
    'button:has-text("Dismiss")',
    'button:has-text("No thanks")',
    'button:has-text("Not now")',
    'button:has-text("Maybe later")',
    'button:has-text("No thank you")',
    'button:has-text("Skip")',
    'button:has-text("Later")',
    'button:has-text("×")',
    'button:has-text("✕")',
    'button:has-text("I understand")',
    'button:has-text("Accept cookies")',
    'button:has-text("Accept Cookies")',
    'button:has-text("Alle akzeptieren")',
    'button:has-text("Akzeptieren")',
    'button:has-text("Tout accepter")',
    'button:has-text("Accepter")',
    'button:has-text("Accepter tout")',
    'button:has-text("J\'accepte")',
    'button:has-text("Aceptar todo")',
    'button:has-text("Aceptar")',
    'button:has-text("Aceptar todas")',
    'button:has-text("Permitirlas todas")',
    'button:has-text("Permitir todas")',
    'button:has-text("Confirmar mis preferencias")',
    'button:has-text("Gestionar las preferencias de consentimiento")',
    'button:has-text("Centro de preferencia de la privacidad")',
    'button:has-text("Accetta tutto")',
    'button:has-text("Accetta")',
    'button:has-text("Aceitar todos")',
    'button:has-text("Aceitar")',
    'button:has-text("Alles accepteren")',
    'button:has-text("Accepteren")',
    'button:has-text("Akceptuję")',
    'button:has-text("Zaakceptuj wszystko")',
    'button:has-text("Zaakceptuj")',
    'button:has-text("Přijmout vše")',
    'button:has-text("Souhlasím")',
    'button:has-text("Prijať všetko")',
    'button:has-text("Súhlasím")',
    'button:has-text("Elfogadom")',
    'button:has-text("Összes elfogadása")',
    'button:has-text("Accept")',
    'button:has-text("Accept toate")',
    'button:has-text("Приемам")',
    'button:has-text("Приемане на всички")',
    'button:has-text("Αποδοχή")',
    'button:has-text("Αποδοχή όλων")',
    'button:has-text("Принять")',
    'button:has-text("Принять все")',
    'button:has-text("Прийняти")',
    'button:has-text("Прийняти все")',
    'button:has-text("Согласен")',
    'button:has-text("Kabul et")',
    'button:has-text("Tümünü kabul et")',
    'button:has-text("قبول")',
    'button:has-text("قبول الكل")',
    'button:has-text("接受")',
    'button:has-text("接受全部")',
    'button:has-text("同意")',
    'button:has-text("同意する")',
    'button:has-text("すべて同意")',
    'button:has-text("동의")',
    'button:has-text("모두 동의")',
    'button:has-text("स्वीकार करें")',
    'button:has-text("Acceptera")',
    'button:has-text("Acceptera alla")',
    'button:has-text("Godta")',
    'button:has-text("Godta alle")',
    'button:has-text("Accepter")',
    'button:has-text("Accepter alle")',
    'button:has-text("Hyväksy")',
    'button:has-text("Hyväksy kaikki")',
    'button:has-text("Samþykkja")',
    'button:has-text("Prihvati")',
    'button:has-text("Prihvati sve")',
    'button:has-text("Прихвати")',
    'button:has-text("Прихвати све")',
    'button:has-text("Прифати")',
    'button:has-text("Прифати ги сите")',
    'button:has-text("Прифати колачиња")',
    'button:has-text("Зачувај")',
    'button:has-text("Зачувајте ги поставките")',
    'button:has-text("Одбиј")',
    'a:has-text("Прифати")',
    'a:has-text("Зачувај")',
    'a:has-text("Зачувајте ги поставките")',
    'a:has-text("Одбиј")',
    'button:has-text("Sprejmi")',
    'button:has-text("Sprejmi vse")',
    'button:has-text("Sutinku")',
    'button:has-text("Pieņemt")',
    'button:has-text("Pieņemt visu")',
    'button:has-text("Nõustun")',
    'button:has-text("OK")',
    'a:has-text("cookies")',
    'a:has-text("Prano")',
    'a:has-text("Ruaj")',
    'a:has-text("Accept")',
    'a:has-text("Accept All")',
    'a:has-text("Select all")',
    'a:has-text("Select All")',
    'a:has-text("I Agree")',
    'a:has-text("Agree")',
    'a:has-text("Accepter")',
    'a:has-text("Aceptar")',
    'a:has-text("Aceitar")',
    'a:has-text("Akzeptieren")',
    'a:has-text("OK")',
    'a:has-text("Close")',
    'a:has-text("No thanks")',
    'a:has-text("Not now")',
    'a:has-text("Skip")',
    'a:has-text("Later")',
    '[id*="cookie"] button',
    '[id*="cookie"] a',
    '[class*="cookie"] button',
    '[class*="cookie"] a',
    '[id*="consent"] button',
    '[id*="consent"] a',
    '[class*="consent"] button',
    '[class*="consent"] a',
    '[class*="banner"] button',
    '[class*="banner"] a[href="#"]',
    '[class*="gdpr"] button',
    '[class*="ccpa"] button',
    '[id*="popup"] button',
    '[id*="popup"] [class*="close"]',
    '[id*="popup"] button[class*="close"]',
    '[class*="popup"] button',
    '[class*="popup"] [class*="close"]',
    '[class*="modal"] button[class*="close"]',
    '[class*="modal"] [aria-label*="close" i]',
    '[class*="newsletter"] button[class*="close"]',
    '[class*="subscribe"] button[class*="close"]',
    '[class*="location"] button:has-text("Continue")',
    '[class*="location"] button',
    '[class*="country"] button:has-text("Continue")',
    '[class*="country"] button',
    '[class*="region"] button:has-text("Continue")',
    '[class*="region"] button',
    '[id*="location"] button',
    '[id*="country"] button',
    '[class*="modal"] button:has-text("Accept all")',
    '[class*="modal"] button:has-text("Accept All")',
    '[class*="modal"] button:has-text("Accept")',
    '[class*="modal"] button:has-text("Agree")',
    '[class*="modal"] button:has-text("OK")',
    '[aria-label*="accept" i]',
    '[aria-label*="agree" i]',
    '[aria-label*="close" i]',
    '[aria-label*="dismiss" i]',
    '[data-testid*="cookie"] button',
    '[data-testid*="consent"] button',
    '[data-testid*="accept"]',
    '[role="button"]:has-text("Accept all")',
    '[role="button"]:has-text("Accept All")',
    '[role="button"]:has-text("Accept")',
    '[role="button"]:has-text("Agree")',
    '[role="button"]:has-text("OK")',
    '[role="button"]:has-text("cookies")',
    '[role="button"]:has-text("Prano")',
    '[role="button"]:has-text("Ruaj")',
    '[role="button"]:has-text("Прифати")',
    '[role="button"]:has-text("Зачувај")',
    '[role="button"]:has-text("Зачувајте ги поставките")',
    '[role="button"]:has-text("Одбиј")',
]

POPUP_SELECTORS_COOKIE = tuple(COOKIE_CONSENT_SELECTORS)

# Newsletter / signup overlays (close/dismiss only)
POPUP_SELECTORS_NEWSLETTER = (
    '[id*="newsletter"] button[class*="close"]',
    '[class*="newsletter"] button[class*="close"]',
    '[class*="modal"] button[class*="close"]',
    'button:has-text("No thanks")',
    'button:has-text("Maybe later")',
    '[aria-label*="close" i]',
    '[aria-label*="dismiss" i]',
)

# Generic modal overlays
POPUP_SELECTORS_MODAL = (
    '[id*="popup"] button[class*="close"]',
    '[class*="popup"] button[class*="close"]',
    '[role="dialog"] button[aria-label*="close" i]',
    '[role="dialog"] [class*="close"]',
)

# Age gate (dismiss/enter only; no "under age" clicks)
POPUP_SELECTORS_AGE_GATE = (
    '[id*="age"] button',
    '[class*="age-gate"] button',
    '[class*="age-verify"] button',
    '[id*="birthday"] button',
)

# Geo / country prompt (close or continue only; no purchase)
POPUP_SELECTORS_GEO = (
    '[class*="geo"] button[class*="close"]',
    '[id*="country"] [class*="close"]',
    '[class*="region"] button[class*="close"]',
)

# Deterministic order for popup pass (cookie → newsletter → modal → age_gate → geo)
POPUP_CATEGORY_ORDER = ("cookie", "newsletter", "modal", "age_gate", "geo")

# Overlay-first order: dialog/banner (modal) before cookie/newsletter (§5 detection layers)
POPUP_CATEGORY_ORDER_OVERLAY_FIRST = ("modal", "cookie", "newsletter", "age_gate", "geo")

# Container selectors used to ensure dismiss clicks happen inside known consent/pop-up containers.
POPUP_CONTAINER_SELECTORS = (
    ".offcanvas-cookie",
    ".cookie-permission",
    "[id*='cookie']",
    "[class*='cookie']",
    "[id*='consent']",
    "[class*='consent']",
    "[class*='gdpr']",
    "[class*='ccpa']",
    "[class*='banner']",
    "[class*='popup']",
    "[class*='modal']",
    "[role='dialog']",
    ".offcanvas",
)

# Bounded attempts per pass (max dismissals per pass; deterministic timing)
MAX_DISMISSALS_PER_PASS = 5
POPUP_VISIBILITY_TIMEOUT_MS = 1000
POPUP_CLICK_TIMEOUT_MS = 2000
POPUP_SETTLE_AFTER_DISMISS_MS = 200

# Safe dismiss keywords (button/link text); minimal set for deterministic matching.
# Only elements whose normalized text matches one of these are considered safe to click.
# Include got it, continue, ×, ✕ so selectors for those buttons succeed.
SAFE_DISMISS_KEYWORDS = frozenset(
    [
        "accept",
        "accept all",
        "agree",
        "allow all",
        "close",
        "confirmar mis preferencias",
        "continue",
        "dismiss",
        "got it",
        "gestionar las preferencias de consentimiento",
        "i accept",
        "maybe later",
        "no thanks",
        "ok",
        "permitir todas",
        "permitirlas todas",
        "×",  # multiplication sign, common close icon
        "✕",  # ballot x, common close icon
    ]
)

# Risky CTA keywords: never click (buy, checkout, allow notifications).
# If element text contains any of these (normalized), do not click.
RISKY_CTA_KEYWORDS = frozenset(
    [
        "buy",
        "checkout",
        "allow notification",
        "enable notification",
        "subscribe",  # newsletter subscribe CTA, not dismiss
    ]
)
