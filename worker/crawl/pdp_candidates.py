"""
PDP candidate discovery: path matching, URL normalization, link extraction.

Uses eTLD+1 for internal links (same site across subdomains, e.g. www.example.com).
Includes product-like container pass: anchors inside containers with 2-of-4 signals
(price, title, image, add-to-cart) are candidates regardless of URL structure.
Validation (2-of-4 rule) and determinism unchanged. Cap applied after dedupe.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from playwright.async_api import Page

from shared.logging import get_logger
from worker.crawl.constants import (
    EXCLUDED_PATH_SEGMENTS,
    MAX_PDP_CANDIDATES,
    PDP_PATH_PATTERNS,
    PRODUCT_CONTAINER_ADD_TO_CART_SELECTORS,
    PRODUCT_CONTAINER_IMAGE_SELECTOR,
    PRODUCT_CONTAINER_MIN_SIGNALS,
    PRODUCT_CONTAINER_SELECTORS,
    PRODUCT_CONTAINER_TITLE_SELECTORS,
)
from worker.crawl.pdp_validation import PRICE_PATTERN

logger = get_logger(__name__)


def get_etld_plus_one(netloc: str) -> str:
    """
    Return eTLD+1 (site domain) for internal link comparison.

    Same eTLD+1 => internal (e.g. foleja.com and www.foleja.com).
    Heuristic: strip leading "www.", then for 3+ parts use last two
    (e.g. shop.example.com -> example.com).
    """
    n = (netloc or "").lower().strip()
    if not n:
        return ""
    if n.startswith("www."):
        n = n[4:]
    parts = n.split(".")
    if len(parts) >= 3:
        return ".".join(parts[-2:])
    return n


def is_pdp_candidate_path(path: str) -> bool:
    """
    Return True if path matches PDP-like URL patterns (case-insensitive).

    Pure function for unit tests.
    """
    path_lower = path.lower().strip()
    if not path_lower or path_lower == "/":
        return False
    for pattern in PDP_PATH_PATTERNS:
        if re.search(pattern, path_lower):
            return True
    return False


def _path_has_excluded_segment(path: str) -> bool:
    """Return True if path contains an excluded segment (account, cart, etc.)."""
    segments = [s.lower() for s in path.strip("/").split("/") if s]
    return bool(segments and any(seg in EXCLUDED_PATH_SEGMENTS for seg in segments))


def normalize_internal_url(href: str, base_url: str) -> Optional[str]:
    """
    Resolve href against base_url; return normalized URL if same-domain and http(s), else None.

    Excludes mailto:, tel:, fragment-only. Pure function for unit tests.
    """
    href = (href or "").strip()
    if not href or href.startswith("mailto:") or href.startswith("tel:") or href.startswith("#"):
        return None
    try:
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        # Normalize: lowercase host, path without trailing slash (except /)
        path = (parsed.path or "/").rstrip("/") or "/"
        return f"{parsed.scheme}://{parsed.netloc.lower()}{path}"
    except Exception:
        return None


def filter_pdp_candidate_urls(
    urls: list[str],
    base_url: str,
    max_candidates: int = MAX_PDP_CANDIDATES,
) -> list[str]:
    """
    Filter URLs to same-site (eTLD+1), PDP-path candidates; exclude account/cart/checkout/logout;
    dedupe and return in input (insertion) order; cap applied after dedupe.

    Pure function for unit tests.
    """
    parsed_base = urlparse(base_url)
    base_site = get_etld_plus_one(parsed_base.netloc or "")
    seen: set[str] = set()
    result: list[str] = []
    for raw in urls:
        normalized = normalize_internal_url(raw, base_url)
        if not normalized:
            continue
        parsed = urlparse(normalized)
        if get_etld_plus_one(parsed.netloc or "") != base_site:
            continue
        path = (parsed.path or "/").lower()
        if _path_has_excluded_segment(path):
            continue
        if not is_pdp_candidate_path(path):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) >= max_candidates:
            break
    return result[:max_candidates]


def filter_product_context_urls(
    urls: list[str],
    base_url: str,
    max_candidates: int = MAX_PDP_CANDIDATES,
) -> list[str]:
    """
    Filter URLs to same-site (eTLD+1), exclude account/cart/checkout; no URL pattern required.

    Use for product-like container links (e.g. /categories/tv/TV-LED-FUEGO-43EL720GTV).
    Dedupe and return in input order; cap applied after dedupe. Pure function for tests.
    """
    parsed_base = urlparse(base_url)
    base_site = get_etld_plus_one(parsed_base.netloc or "")
    seen: set[str] = set()
    result: list[str] = []
    for raw in urls:
        normalized = normalize_internal_url(raw, base_url)
        if not normalized:
            continue
        parsed = urlparse(normalized)
        if get_etld_plus_one(parsed.netloc or "") != base_site:
            continue
        path = (parsed.path or "/").lower()
        if _path_has_excluded_segment(path):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) >= max_candidates:
            break
    return result[:max_candidates]


async def _container_has_min_signals(container, min_signals: int) -> bool:
    """
    Return True if the container (Locator) has at least min_signals of:
    price, title, image, add-to-cart. Uses PRICE_PATTERN for price.
    """
    count = 0
    try:
        # Price: text content of container
        text = await container.inner_text()
        if PRICE_PATTERN.search(text):
            count += 1
        if count >= min_signals:
            return True
        # Title
        for sel in PRODUCT_CONTAINER_TITLE_SELECTORS:
            if await container.locator(sel).first.count() > 0:
                count += 1
                break
        if count >= min_signals:
            return True
        # Image
        if await container.locator(PRODUCT_CONTAINER_IMAGE_SELECTOR).first.count() > 0:
            count += 1
        if count >= min_signals:
            return True
        # Add-to-cart
        for sel in PRODUCT_CONTAINER_ADD_TO_CART_SELECTORS:
            if await container.locator(sel).first.count() > 0:
                count += 1
                break
    except Exception:
        pass
    return count >= min_signals


async def _is_inside_nav_or_footer(link_handle) -> bool:
    """Return True if the link is inside nav or footer (and not inside a product container)."""
    try:
        # Check if any ancestor is nav or footer
        return await link_handle.evaluate("""(el) => {
            let n = el;
            while (n) {
                const tag = (n.tagName || '').toLowerCase();
                if (tag === 'nav' || tag === 'footer') return true;
                n = n.parentElement;
            }
            return false;
        }""")
    except Exception:
        return False


async def extract_pdp_candidate_links(
    page: Page,
    base_url: str,
    max_candidates: int = MAX_PDP_CANDIDATES,
) -> list[str]:
    """
    Extract internal PDP candidate links from the page (after page-ready + scroll).

    Two passes (DOM order); cap applied after dedupe.
    1. Context pass: links inside product-like containers (.product, .product-card, etc.)
       that have at least 2-of-4 signals (price, title, image, add-to-cart). Included
       even when URL does not match PDP_PATH_PATTERNS (e.g. /categories/tv/MAR-200000509).
    2. Pattern pass: links from product-grid/main that match PDP path patterns.
    Links in nav/footer are skipped unless from the context pass (inside a product container).
    Same-site by eTLD+1; exclude account/cart/checkout; dedupe by normalized URL.
    """
    base_site = get_etld_plus_one(urlparse(base_url).netloc or "")
    hrefs: list[str] = []
    seen_urls: set[str] = set()

    def _same_site(netloc: str) -> bool:
        return get_etld_plus_one(netloc or "") == base_site

    def _accept_link(normalized: str, require_path_pattern: bool) -> bool:
        if not normalized or normalized in seen_urls:
            return False
        parsed = urlparse(normalized)
        if not _same_site(parsed.netloc or ""):
            return False
        path = (parsed.path or "/").lower()
        if _path_has_excluded_segment(path):
            return False
        if require_path_pattern and not is_pdp_candidate_path(path):
            return False
        return True

    # Pass 1: product-like containers with 2-of-4 signals
    for container_sel in PRODUCT_CONTAINER_SELECTORS:
        try:
            containers = await page.locator(container_sel).all()
            for container in containers:
                if len(hrefs) >= max_candidates:
                    break
                try:
                    if not await _container_has_min_signals(
                        container, PRODUCT_CONTAINER_MIN_SIGNALS
                    ):
                        continue
                    links = await container.locator("a[href]").all()
                    for link in links:
                        if len(hrefs) >= max_candidates:
                            break
                        href = await link.get_attribute("href")
                        if not href:
                            continue
                        normalized = normalize_internal_url(href, base_url)
                        if not _accept_link(normalized, require_path_pattern=False):
                            continue
                        seen_urls.add(normalized)
                        hrefs.append(normalized)
                except Exception:
                    continue
            if len(hrefs) >= max_candidates:
                break
        except Exception:
            continue

    context_pass_count = len(hrefs)

    # Pass 2: pattern-based selectors; skip links that are only in nav/footer
    pattern_selectors = [
        "[class*='product-grid'] a[href]",
        "[class*='featured-products'] a[href]",
        "[class*='products'] a[href]",
        "main a[href]",
        "a[href]",
    ]
    for selector in pattern_selectors:
        try:
            links = await page.locator(selector).all()
            for link in links:
                if len(hrefs) >= max_candidates:
                    break
                try:
                    if await _is_inside_nav_or_footer(link):
                        continue
                    href = await link.get_attribute("href")
                    if not href:
                        continue
                    normalized = normalize_internal_url(href, base_url)
                    if not _accept_link(normalized, require_path_pattern=True):
                        continue
                    seen_urls.add(normalized)
                    hrefs.append(normalized)
                except Exception:
                    continue
            if len(hrefs) >= max_candidates:
                break
        except Exception:
            continue

    pattern_pass_count = len(hrefs) - context_pass_count
    result = list(dict.fromkeys(hrefs))[:max_candidates]
    logger.info(
        "pdp_candidate_extraction_complete",
        context_pass_count=context_pass_count,
        pattern_pass_count=pattern_pass_count,
        total_before_cap=len(hrefs),
        final_count=len(result),
        max_candidates=max_candidates,
    )
    return result
