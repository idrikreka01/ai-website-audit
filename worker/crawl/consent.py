"""
Pre-consent injection for vendor-managed cookie banners.

Applies vendor scripts before navigation (init scripts) and after navigation
(main document + iframes) to suppress consent panels.
Per TECH_SPEC_V1.1.md §5 Popup Handling Policy v1.7.
"""

from __future__ import annotations

from typing import Iterable

from playwright.async_api import BrowserContext, Page

VENDOR_ONETRUST = "onetrust"
VENDOR_SHOPWARE = "shopware"
VENDOR_COOKIEBOT = "cookiebot"
VENDOR_TRUSTARC = "trustarc"
VENDOR_QUANTCAST = "quantcast"
VENDOR_DIDOMI = "didomi"
VENDOR_USERCENTRICS = "usercentrics"
VENDOR_COMPLIANZ = "complianz"
VENDOR_CIVIC = "civic"
VENDOR_OSANO = "osano"
VENDOR_IUBENDA = "iubenda"

DEFAULT_VENDORS: tuple[str, ...] = (
    VENDOR_ONETRUST,
    VENDOR_SHOPWARE,
    VENDOR_COOKIEBOT,
    VENDOR_TRUSTARC,
    VENDOR_QUANTCAST,
    VENDOR_DIDOMI,
    VENDOR_USERCENTRICS,
    VENDOR_COMPLIANZ,
    VENDOR_CIVIC,
    VENDOR_OSANO,
    VENDOR_IUBENDA,
)


def _onetrust_init_script() -> str:
    return """
(() => {
  try {
    const now = new Date().toISOString();
    const consent = [
      "isIABGlobal=false",
      `datestamp=${encodeURIComponent(now)}`,
      "version=6.18.0",
      "consentId=00000000-0000-0000-0000-000000000000",
      "interactionCount=1",
      "landingPath=NotLandingPage",
      "groups=C0001:1,C0002:1,C0003:1,C0004:1,C0005:1"
    ].join("&");
    document.cookie = `OptanonAlertBoxClosed=${encodeURIComponent(now)}; path=/; SameSite=Lax`;
    document.cookie = `OptanonConsent=${consent}; path=/; SameSite=Lax`;
    try { localStorage.setItem("OptanonAlertBoxClosed", now); } catch (e) {}
    try { localStorage.setItem("OptanonConsent", consent); } catch (e) {}
  } catch (e) {}
})();
"""


def _shopware_init_script() -> str:
    return """
(() => {
  try {
    const CONTAINERS = [
      '.offcanvas-cookie',
      '.cookie-permission',
      '[class*="cookie"]',
      '[class*="consent"]',
      '[id*="cookie"]',
      '[id*="consent"]'
    ];
    const ACCEPT_SELECTORS = [
      '.js-offcanvas-cookie-accept-all',
      '#accept-cookies',
      '#accept-all-cookies',
      '[data-testid*="accept"]',
      '.cookie-permission-actions button',
      '.offcanvas-cookie button'
    ];
    const ACCEPT_TEXT_RE = new RegExp(
      '(accept|allow all|agree|consent|prano|pajtohu|permitir|aceptar|accetta|aceitar)', 'i');

    const findContainer = () => {
      for (const sel of CONTAINERS) {
        const el = document.querySelector(sel);
        if (el) return el;
      }
      return null;
    };

    const trySelectors = (root) => {
      for (const sel of ACCEPT_SELECTORS) {
        const el = (root || document).querySelector(sel);
        if (el) return el;
      }
      return null;
    };

    const tryTextMatch = (root, roleSelector) => {
      const nodes = (root || document).querySelectorAll(roleSelector);
      for (const el of nodes) {
        const text = (el.innerText || el.textContent || '').trim();
        const aria = (el.getAttribute('aria-label') || '').trim();
        if (ACCEPT_TEXT_RE.test(text) || ACCEPT_TEXT_RE.test(aria)) return el;
      }
      return null;
    };

    const tryClick = () => {
      const container = findContainer();
      if (!container) return false;
      let el = trySelectors(container);
      if (!el) el = container.querySelector('[id*="accept"], [class*="accept"], [name*="accept"]');
      if (!el) el = tryTextMatch(container, 'button');
      if (!el) el = tryTextMatch(container, '[role="button"]');
      if (!el) el = tryTextMatch(container, 'a');
      if (el) {
        el.click();
        return true;
      }
      return false;
    };

    if (!tryClick()) {
      const obs = new MutationObserver(() => {
        if (tryClick()) obs.disconnect();
      });
      obs.observe(document.documentElement || document.body, { childList: true, subtree: true });
    }
  } catch (e) {}
})();
"""


def _dom_click_script(
    *,
    root_selectors: list[str],
    accept_selectors: list[str],
    accept_text_re: str,
) -> str:
    roots = ",".join(root_selectors)
    selectors = ",".join(accept_selectors)
    return f"""
(() => {{
  try {{
    const ROOTS = `{roots}`;
    const ACCEPT_SELECTORS = `{selectors}`;
    const ACCEPT_TEXT_RE = /{accept_text_re}/i;

    const findRoot = () => {{
      if (!ROOTS) return null;
      const el = document.querySelector(ROOTS);
      return el || null;
    }};

    const findBySelectors = (root) => {{
      if (!ACCEPT_SELECTORS) return null;
      return (root || document).querySelector(ACCEPT_SELECTORS);
    }};

    const findByText = (root, roleSelector) => {{
      const nodes = (root || document).querySelectorAll(roleSelector);
      for (const el of nodes) {{
        const text = (el.innerText || el.textContent || '').trim();
        const aria = (el.getAttribute('aria-label') || '').trim();
        if (ACCEPT_TEXT_RE.test(text) || ACCEPT_TEXT_RE.test(aria)) return el;
      }}
      return null;
    }};

    const tryClick = () => {{
      const root = findRoot();
      if (!root) return false;
      let el = findBySelectors(root);
      if (!el) el = root.querySelector('[id*=\"accept\"], [class*=\"accept\"], [name*=\"accept\"]');
      if (!el) el = findByText(root, 'button');
      if (!el) el = findByText(root, '[role=\"button\"]');
      if (!el) el = findByText(root, 'a');
      if (el) {{
        el.click();
        return true;
      }}
      return false;
    }};

    if (!tryClick()) {{
      const obs = new MutationObserver(() => {{
        if (tryClick()) obs.disconnect();
      }});
      obs.observe(document.documentElement || document.body, {{ childList: true, subtree: true }});
    }}
  }} catch (e) {{}}
}})();
"""


def _cookiebot_init_script() -> str:
    return _dom_click_script(
        root_selectors=[
            "#CybotCookiebotDialog",
            "#CookiebotDialog",
            ".CookiebotDialog",
        ],
        accept_selectors=[
            "#CybotCookiebotDialogBodyLevelButtonAccept",
            "#CybotCookiebotDialogBodyButtonAccept",
            "#CookiebotDialogBodyLevelButtonAccept",
            "#CookiebotDialogBodyButtonAccept",
        ],
        accept_text_re=r"(accept|allow|agree|ok|consent)",
    )


def _trustarc_init_script() -> str:
    return _dom_click_script(
        root_selectors=[
            "[id*='truste']",
            "[class*='truste']",
            "[class*='trustarc']",
        ],
        accept_selectors=[
            "#truste-consent-button",
            "#truste-consent-button-handler",
            ".truste-consent-button",
        ],
        accept_text_re=r"(accept|allow|agree|ok|consent)",
    )


def _quantcast_init_script() -> str:
    return _dom_click_script(
        root_selectors=[
            "#qc-cmp2-ui",
            ".qc-cmp2-container",
            ".qc-cmp2-popup",
        ],
        accept_selectors=[
            "button[mode='primary']",
            ".qc-cmp2-summary-buttons button",
        ],
        accept_text_re=r"(accept|allow|agree|ok|consent)",
    )


def _didomi_init_script() -> str:
    return _dom_click_script(
        root_selectors=[
            "#didomi-notice",
            "#didomi-popup",
            ".didomi-consent-popup",
        ],
        accept_selectors=[
            ".didomi-continue-without-agreeing",
            ".didomi-accept-button",
        ],
        accept_text_re=r"(accept|allow|agree|ok|consent|tout accepter|aceptar)",
    )


def _usercentrics_init_script() -> str:
    return _dom_click_script(
        root_selectors=[
            "#usercentrics-root",
            ".uc-root",
            "#uc-center-container",
        ],
        accept_selectors=[
            "button[data-testid='uc-accept-all-button']",
            ".uc-accept-all-button",
        ],
        accept_text_re=r"(accept|allow|agree|ok|consent)",
    )


def _complianz_init_script() -> str:
    return _dom_click_script(
        root_selectors=[
            "#cmplz-cookiebanner-container",
            ".cmplz-cookiebanner",
        ],
        accept_selectors=[
            ".cmplz-btn.cmplz-accept",
            ".cmplz-accept",
        ],
        accept_text_re=r"(accept|allow|agree|ok|consent)",
    )


def _civic_init_script() -> str:
    return _dom_click_script(
        root_selectors=[
            "#ccc",
            "#ccc-notify",
            ".ccc",
        ],
        accept_selectors=[
            ".ccc-notify-accept",
            ".ccc-accept",
        ],
        accept_text_re=r"(accept|allow|agree|ok|consent)",
    )


def _osano_init_script() -> str:
    return _dom_click_script(
        root_selectors=[
            ".osano-cm-window",
            ".osano-cm-dialog",
        ],
        accept_selectors=[
            ".osano-cm-accept",
            ".osano-cm-accept-all",
        ],
        accept_text_re=r"(accept|allow|agree|ok|consent)",
    )


def _iubenda_init_script() -> str:
    return _dom_click_script(
        root_selectors=[
            "#iubenda-cs-banner",
            ".iubenda-cs-container",
        ],
        accept_selectors=[
            ".iubenda-cs-accept-btn",
            ".iubenda-cs-btn-primary",
        ],
        accept_text_re=r"(accept|allow|agree|ok|consent)",
    )


def get_preconsent_scripts(vendors: Iterable[str]) -> list[tuple[str, str]]:
    scripts: list[tuple[str, str]] = []
    for v in vendors:
        if v == VENDOR_ONETRUST:
            scripts.append((v, _onetrust_init_script()))
        elif v == VENDOR_SHOPWARE:
            scripts.append((v, _shopware_init_script()))
        elif v == VENDOR_COOKIEBOT:
            scripts.append((v, _cookiebot_init_script()))
        elif v == VENDOR_TRUSTARC:
            scripts.append((v, _trustarc_init_script()))
        elif v == VENDOR_QUANTCAST:
            scripts.append((v, _quantcast_init_script()))
        elif v == VENDOR_DIDOMI:
            scripts.append((v, _didomi_init_script()))
        elif v == VENDOR_USERCENTRICS:
            scripts.append((v, _usercentrics_init_script()))
        elif v == VENDOR_COMPLIANZ:
            scripts.append((v, _complianz_init_script()))
        elif v == VENDOR_CIVIC:
            scripts.append((v, _civic_init_script()))
        elif v == VENDOR_OSANO:
            scripts.append((v, _osano_init_script()))
        elif v == VENDOR_IUBENDA:
            scripts.append((v, _iubenda_init_script()))
    return scripts


async def add_preconsent_init_scripts(context: BrowserContext, vendors: Iterable[str]) -> list[str]:
    applied: list[str] = []
    for vendor, script in get_preconsent_scripts(vendors):
        await context.add_init_script(script)
        applied.append(vendor)
    return applied


async def apply_preconsent_in_frames(page: Page, vendors: Iterable[str]) -> dict:
    """Apply pre-consent scripts in main document and all iframes.

    Returns dict with applied_vendors and frame_count.
    """
    scripts = get_preconsent_scripts(vendors)
    applied_vendors = [v for v, _ in scripts]
    frame_count = 0

    async def _apply_in_frame(frame) -> bool:
        applied_any = False
        for _, script in scripts:
            try:
                await frame.evaluate(script)
                applied_any = True
            except Exception:
                continue
        return applied_any

    for frame in page.frames:
        if await _apply_in_frame(frame):
            frame_count += 1

    return {"applied_vendors": applied_vendors, "frame_count": frame_count}
