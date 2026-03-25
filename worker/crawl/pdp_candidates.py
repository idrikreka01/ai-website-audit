# ABOUTME: PDP candidate link discovery.
# ABOUTME: Optional HTTP-crawl PDP candidate discovery mode.
"""
PDP candidate discovery: path matching, URL normalization, link extraction.

Uses eTLD+1 for internal links (same site across subdomains, e.g. www.example.com).
Includes product-like container pass: anchors inside containers with 2-of-4 signals
(price, title, image, add-to-cart) are candidates regardless of URL structure.
Validation (2-of-4 rule) and determinism unchanged. Cap applied after dedupe.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import re
import os
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
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


_HTTP_PDP_DEFAULT_MAX_PAGES = 25
_HTTP_PDP_TIMEOUT_SEC = 20


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)

PRODUCT_PATH_WORDS = [
    "/products/",
    "/product/",
    "/prodotti/",
    "/produkte/",
    "/produto/",
    "/item/",
    "/p/",
]

COLLECTION_HINTS = [
    "shop",
    "collection",
    "collections",
    "catalog",
    "products",
    "store",
    "new arrivals",
    "all products",
    "best sellers",
]

CRAWL_HINTS = [
    "shop",
    "collection",
    "collections",
    "catalog",
    "products",
    "store",
    "new",
    "sale",
    "featured",
    "category",
    "categories",
    "brands",
    "women",
    "men",
    "kids",
]

IGNORE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".pdf",
    ".zip",
}


@dataclass(frozen=True)
class _HttpProductHit:
    url: str
    source_url: str
    anchor_text: str
    depth: int
    validation_reason: str = ""


def _http_build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _http_normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _http_clean_url(url: str) -> str:
    parsed = urlparse(url)
    cleaned = parsed._replace(fragment="", query="")
    return urlunparse(cleaned)


def _http_looks_like_asset(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    return any(path.endswith(ext) for ext in IGNORE_EXTENSIONS)


def _http_looks_like_product(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    return any(word in path for word in PRODUCT_PATH_WORDS)


def _http_looks_unhelpful(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    blocked_parts = [
        "/account",
        "/cart",
        "/checkout",
        "/search",
        "/blogs",
        "/blog",
        "/pages/",
        "/policies/",
        "/policy",
        "/contact",
        "/help",
        "/faq",
        "/about",
        "/login",
        "/register",
    ]
    return any(part in path for part in blocked_parts)


def _http_score_collection_link(url: str, anchor_text: str, tag: Tag) -> int:
    score = 0
    blob = _http_normalize_space(
        " ".join(
            [
                urlparse(url).path or "",
                anchor_text,
                " ".join(tag.get("class", []) or []),
                tag.get("id", "") or "",
                tag.get("aria-label", "") or "",
            ]
        )
    )

    for hint in COLLECTION_HINTS:
        if hint in blob:
            score += 20

    if "/collections/" in blob:
        score += 35
    if "/shop" in blob or "/catalog" in blob:
        score += 25
    if tag.find_parent(["nav", "header"]):
        score += 10
    if anchor_text:
        score += 5

    return score


def _http_score_crawl_link(url: str, anchor_text: str, tag: Tag) -> int:
    path = (urlparse(url).path or "").lower()
    blob = _http_normalize_space(
        " ".join(
            [
                path,
                anchor_text,
                " ".join(tag.get("class", []) or []),
                tag.get("id", "") or "",
                tag.get("aria-label", "") or "",
            ]
        )
    )

    score = 0
    for hint in CRAWL_HINTS:
        if hint in blob:
            score += 12

    if any(
        part in path
        for part in ["/collections/", "/collection/", "/shop", "/catalog", "/category"]
    ):
        score += 25
    if tag.find_parent(["nav", "header", "main", "section"]):
        score += 6
    if anchor_text:
        score += 4
    if _http_looks_unhelpful(url):
        score -= 40

    return score


def _http_extract_links(
    page_url: str,
    html_text: str,
    root_site: str,
) -> tuple[list[_HttpProductHit], list[tuple[int, str, str]]]:
    soup = BeautifulSoup(html_text, "html.parser")
    product_hits: dict[str, _HttpProductHit] = {}
    collection_candidates: dict[str, tuple[int, str, str]] = {}

    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "") or ""
        absolute_url = _http_clean_url(urljoin(page_url, href))
        if not absolute_url.startswith(("http://", "https://")):
            continue

        candidate_netloc = urlparse(absolute_url).netloc or ""
        if get_etld_plus_one(candidate_netloc) != root_site:
            continue
        if _http_looks_like_asset(absolute_url):
            continue

        anchor_text = _http_normalize_space(" ".join(tag.stripped_strings))

        if _http_looks_like_product(absolute_url):
            product_hits.setdefault(
                absolute_url,
                _HttpProductHit(
                    url=absolute_url,
                    source_url=page_url,
                    anchor_text=anchor_text,
                    depth=0,
                ),
            )
            continue

        score = max(_http_score_collection_link(absolute_url, anchor_text, tag), _http_score_crawl_link(absolute_url, anchor_text, tag))
        if score >= 12:
            prev = collection_candidates.get(absolute_url)
            if not prev or score > prev[0]:
                collection_candidates[absolute_url] = (score, absolute_url, anchor_text)

    ordered_collections = sorted(
        collection_candidates.values(),
        key=lambda item: item[0],
        reverse=True,
    )
    return list(product_hits.values()), ordered_collections


def _http_validate_product_html(html_text: str) -> tuple[bool, str]:
    lowered = (html_text or "").lower()
    score = 0
    reasons: list[str] = []

    signals = [
        ('og:type" content="product', 45, "og:type product"),
        ('property="product:price:amount', 25, "product price meta"),
        ('name="twitter:label1" content="price', 15, "twitter price meta"),
        ("/cart/add", 35, "cart add form"),
        ("add to cart", 25, "add to cart text"),
        ("product-form", 20, "product form"),
        ('"@type":"product"', 35, "schema.org product"),
        ('"@type": "product"', 35, "schema.org product"),
        ("/products/", 5, "product path"),
    ]

    for marker, points, label in signals:
        if marker in lowered:
            score += points
            reasons.append(label)

    if score >= 45:
        return True, ", ".join(reasons[:4]) if reasons else "validated"
    return False, ", ".join(reasons[:4]) if reasons else "no strong product signals"


def _http_fetch_and_validate_product(
    session: requests.Session,
    url: str,
    cache: dict[str, tuple[bool, str]],
) -> tuple[bool, str]:
    if url in cache:
        return cache[url]

    try:
        response = session.get(url, timeout=_HTTP_PDP_TIMEOUT_SEC)
        response.raise_for_status()
    except requests.RequestException as exc:
        cache[url] = (False, str(exc))
        return cache[url]

    cache[url] = _http_validate_product_html(response.text)
    return cache[url]


def _discover_products_via_http_crawl(
    homepage_url: str,
    *,
    max_pages: int,
    max_products: int,
) -> list[str]:
    session = _http_build_session()
    root = _http_clean_url(homepage_url)
    root_site = get_etld_plus_one(urlparse(root).netloc or "")

    queue: deque[tuple[int, str]] = deque([(0, root)])
    visited: set[str] = set()
    found_products: dict[str, _HttpProductHit] = {}
    validation_cache: dict[str, tuple[bool, str]] = {}

    while queue and len(visited) < max_pages and len(found_products) < max_products:
        depth, url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        try:
            response = session.get(url, timeout=_HTTP_PDP_TIMEOUT_SEC)
            response.raise_for_status()
            html_text = response.text
            status = "ok"
        except requests.RequestException:
            continue

        page_products, collection_candidates = _http_extract_links(
            url,
            html_text,
            root_site,
        )

        for hit in page_products:
            is_valid, reason = _http_fetch_and_validate_product(
                session,
                hit.url,
                validation_cache,
            )
            if not is_valid:
                continue
            if hit.url not in found_products:
                found_products[hit.url] = _HttpProductHit(
                    url=hit.url,
                    source_url=hit.source_url,
                    anchor_text=hit.anchor_text,
                    depth=hit.depth,
                    validation_reason=reason,
                )
            if len(found_products) >= max_products:
                break

        if len(found_products) >= max_products:
            break

        for _score, candidate_url, _anchor_text in collection_candidates:
            if candidate_url in visited:
                continue
            if any(existing_url == candidate_url for _, existing_url in queue):
                continue
            queue.append((depth + 1, candidate_url))

    product_list = [hit.url for hit in found_products.values()]
    return product_list[:max_products]


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
    discovery_mode = (os.getenv("PDP_DISCOVERY_MODE") or "old").strip().lower()
    if discovery_mode in {"new", "http", "http_new", "script"}:
        homepage_url = base_url
        logger.info(
            "pdp_candidate_discovery_mode_http_new_start",
            base_url=base_url,
            homepage_url=homepage_url,
            max_candidates=max_candidates,
            max_pages=_HTTP_PDP_DEFAULT_MAX_PAGES,
        )
        discovered_urls = await asyncio.to_thread(
            _discover_products_via_http_crawl,
            homepage_url,
            max_pages=_HTTP_PDP_DEFAULT_MAX_PAGES,
            max_products=max_candidates,
        )
        result = filter_product_context_urls(
            discovered_urls,
            base_url,
            max_candidates=max_candidates,
        )
        logger.info(
            "pdp_candidate_discovery_mode_http_new_complete",
            discovered_count=len(discovered_urls),
            final_count=len(result),
            max_candidates=max_candidates,
        )
        return result

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
