"""
PDP candidate discovery: path matching, URL normalization, link extraction.

Includes product-like container pass for sites without /product-style URLs.
Validation (2-of-4 rule) and determinism unchanged.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from playwright.async_api import Page

from worker.crawl.constants import (
    EXCLUDED_PATH_SEGMENTS,
    MAX_PDP_CANDIDATES,
    PDP_PATH_PATTERNS,
    PRODUCT_LIKE_CONTAINER_SELECTORS,
)


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
    Filter URLs to same-domain, PDP-path candidates; exclude account/cart/checkout/logout;
    dedupe and return in input (insertion) order, capped at max_candidates.

    Pure function for unit tests.
    """
    parsed_base = urlparse(base_url)
    base_netloc = (parsed_base.netloc or "").lower()
    seen: set[str] = set()
    result: list[str] = []
    for raw in urls:
        normalized = normalize_internal_url(raw, base_url)
        if not normalized:
            continue
        parsed = urlparse(normalized)
        if (parsed.netloc or "").lower() != base_netloc:
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
    Filter URLs to same-domain, exclude account/cart/checkout; no URL pattern required.

    Use for product-like container links (e.g. /categories/tv/TV-LED-FUEGO-43EL720GTV).
    Dedupe and return in input order, capped at max_candidates. Pure function for tests.
    """
    parsed_base = urlparse(base_url)
    base_netloc = (parsed_base.netloc or "").lower()
    seen: set[str] = set()
    result: list[str] = []
    for raw in urls:
        normalized = normalize_internal_url(raw, base_url)
        if not normalized:
            continue
        parsed = urlparse(normalized)
        if (parsed.netloc or "").lower() != base_netloc:
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


async def extract_pdp_candidate_links(
    page: Page,
    base_url: str,
    max_candidates: int = MAX_PDP_CANDIDATES,
) -> list[str]:
    """
    Extract internal PDP candidate links from the page (after page-ready + scroll).

    Two passes (DOM order):
    1. Product-like containers: links inside .product, .product-card, [data-product], etc.
       Included even when URL does not match PDP_PATH_PATTERNS (e.g. /categories/tv/SKU).
    2. Product grids / featured / main: links required to match PDP path patterns.

    Same-domain, exclude account/cart/checkout; dedupe by normalized URL, cap unchanged.
    """
    base_netloc = urlparse(base_url).netloc.lower()

    # (selector, require_path_pattern): product-like first (no pattern), then pattern-based
    pattern_selectors = [
        "[class*='product-grid'] a[href]",
        "[class*='featured-products'] a[href]",
        "[class*='products'] a[href]",
        "main a[href]",
        "a[href]",
    ]
    selector_specs: list[tuple[str, bool]] = [
        (sel, False) for sel in PRODUCT_LIKE_CONTAINER_SELECTORS
    ] + [(sel, True) for sel in pattern_selectors]

    hrefs: list[str] = []
    seen_paths: set[str] = set()
    for selector, require_path_pattern in selector_specs:
        try:
            links = await page.locator(selector).all()
            for link in links:
                href = await link.get_attribute("href")
                if not href:
                    continue
                normalized = normalize_internal_url(href, base_url)
                if not normalized:
                    continue
                parsed = urlparse(normalized)
                if (parsed.netloc or "").lower() != base_netloc:
                    continue
                path = (parsed.path or "/").lower()
                if _path_has_excluded_segment(path):
                    continue
                if require_path_pattern and not is_pdp_candidate_path(path):
                    continue
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                hrefs.append(normalized)
                if len(hrefs) >= max_candidates:
                    break
            if len(hrefs) >= max_candidates:
                break
        except Exception:
            continue
    # Dedupe (preserve insertion order) and cap
    hrefs = list(dict.fromkeys(hrefs))[:max_candidates]
    return hrefs
