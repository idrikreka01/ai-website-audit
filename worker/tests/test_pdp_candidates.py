"""
Unit tests for PDP candidate link filtering and normalization (pure functions).

Covers: eTLD+1 / same-site subdomains, external exclusion, category URLs,
ordering/cap, dedupe, nav/footer exclusion, and existing pattern-based selection.
"""

from __future__ import annotations

import pytest

from worker.crawl import (
    extract_pdp_candidate_links,
    filter_pdp_candidate_urls,
    filter_product_context_urls,
    get_etld_plus_one,
    is_pdp_candidate_path,
    normalize_internal_url,
)


def test_is_pdp_candidate_path_product():
    assert is_pdp_candidate_path("/product/foo") is True
    assert is_pdp_candidate_path("/products/bar") is True
    assert is_pdp_candidate_path("/Product/foo") is True


def test_is_pdp_candidate_path_p_item():
    assert is_pdp_candidate_path("/p/123") is True
    assert is_pdp_candidate_path("/item/abc") is True
    assert is_pdp_candidate_path("/items/") is True


def test_is_pdp_candidate_path_shopify():
    assert is_pdp_candidate_path("/collections/sale/products/thing") is True
    assert is_pdp_candidate_path("/products/something") is True


def test_is_pdp_candidate_path_shop():
    assert is_pdp_candidate_path("/shop/widget") is True


def test_is_pdp_candidate_path_rejects_root_and_non_pdp():
    assert is_pdp_candidate_path("/") is False
    assert is_pdp_candidate_path("/about") is False
    assert is_pdp_candidate_path("/contact") is False


def test_normalize_internal_url_same_domain():
    base = "https://example.com/"
    assert normalize_internal_url("/product/1", base) == "https://example.com/product/1"
    assert (
        normalize_internal_url("https://example.com/product/2", base)
        == "https://example.com/product/2"
    )


def test_normalize_internal_url_rejects_mailto_tel():
    base = "https://example.com/"
    assert normalize_internal_url("mailto:foo@example.com", base) is None
    assert normalize_internal_url("tel:+1234567890", base) is None
    assert normalize_internal_url("#section", base) is None


def test_normalize_internal_url_rejects_empty():
    assert normalize_internal_url("", "https://example.com/") is None
    assert normalize_internal_url("   ", "https://example.com/") is None


def test_filter_pdp_candidate_urls_same_domain_only():
    base = "https://example.com/"
    urls = [
        "https://example.com/product/a",
        "https://other.com/product/b",
        "https://example.com/products/c",
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    assert len(out) == 2
    assert all("example.com" in u for u in out)
    assert "https://other.com/product/b" not in out


def test_filter_pdp_candidate_urls_excludes_account_cart():
    base = "https://example.com/"
    urls = [
        "https://example.com/product/ok",
        "https://example.com/cart",
        "https://example.com/checkout",
        "https://example.com/account",
        "https://example.com/products/ok2",
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    assert "https://example.com/product/ok" in out or "https://example.com/products/ok2" in out
    assert "https://example.com/cart" not in out
    assert "https://example.com/checkout" not in out
    assert "https://example.com/account" not in out


def test_filter_pdp_candidate_urls_dedupe_and_cap():
    base = "https://example.com/"
    urls = ["https://example.com/product/x"] * 5 + [
        "https://example.com/products/y",
        "https://example.com/products/z",
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=3)
    assert len(out) <= 3
    assert len(out) == len(set(out))


def test_filter_pdp_candidate_urls_preserves_insertion_order():
    """Output order follows input order (DOM/insertion order), not sorted."""
    base = "https://example.com/"
    urls = [
        "https://example.com/products/z",
        "https://example.com/product/a",
        "https://example.com/products/m",
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    assert out == [
        "https://example.com/products/z",
        "https://example.com/product/a",
        "https://example.com/products/m",
    ]


# --- Product-context (non-pattern) URLs ---


def test_filter_product_context_urls_includes_non_pattern_urls():
    """Product-context filter includes URLs that do not match PDP_PATH_PATTERNS."""
    base = "https://example.com/"
    urls = [
        "https://example.com/categories/tv/TV-LED-FUEGO-43EL720GTV",
        "https://example.com/shop/item/xyz-123",
    ]
    out = filter_product_context_urls(urls, base, max_candidates=10)
    assert len(out) == 2
    assert "https://example.com/categories/tv/TV-LED-FUEGO-43EL720GTV" in out
    assert "https://example.com/shop/item/xyz-123" in out


def test_filter_product_context_urls_excludes_account_cart():
    """Product-context filter still excludes account/cart/checkout."""
    base = "https://example.com/"
    urls = [
        "https://example.com/categories/tv/TV-LED-FUEGO-43EL720GTV",
        "https://example.com/cart",
        "https://example.com/account",
    ]
    out = filter_product_context_urls(urls, base, max_candidates=10)
    assert "https://example.com/categories/tv/TV-LED-FUEGO-43EL720GTV" in out
    assert "https://example.com/cart" not in out
    assert "https://example.com/account" not in out


def test_filter_product_context_urls_preserves_order_and_cap():
    """Product-context filter preserves insertion order and enforces cap."""
    base = "https://example.com/"
    urls = [
        "https://example.com/categories/tv/A",
        "https://example.com/categories/tv/B",
        "https://example.com/categories/tv/C",
        "https://example.com/categories/tv/D",
    ]
    out = filter_product_context_urls(urls, base, max_candidates=2)
    assert len(out) == 2
    assert out[0] == "https://example.com/categories/tv/A"
    assert out[1] == "https://example.com/categories/tv/B"


def test_filter_product_context_urls_cap_enforced():
    """Product-context filter enforces max_candidates cap."""
    base = "https://example.com/"
    urls = [f"https://example.com/cat/item-{i}" for i in range(25)]
    out = filter_product_context_urls(urls, base, max_candidates=10)
    assert len(out) == 10


def test_filter_pdp_candidate_urls_rejects_non_pattern_urls():
    """Pattern-based filter still rejects URLs that don't match PDP_PATH_PATTERNS."""
    base = "https://example.com/"
    urls = [
        "https://example.com/categories/tv/TV-LED-FUEGO-43EL720GTV",
        "https://example.com/product/valid",
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    assert "https://example.com/categories/tv/TV-LED-FUEGO-43EL720GTV" not in out
    assert "https://example.com/product/valid" in out


# --- eTLD+1 and same-site subdomain ---


def test_get_etld_plus_one_strips_www():
    """Same eTLD+1 for bare domain and www."""
    assert get_etld_plus_one("www.foleja.com") == "foleja.com"
    assert get_etld_plus_one("foleja.com") == "foleja.com"
    assert get_etld_plus_one("www.example.com") == "example.com"
    assert get_etld_plus_one("example.com") == "example.com"


def test_get_etld_plus_one_subdomain():
    """Subdomains normalize to same site (last two parts)."""
    assert get_etld_plus_one("shop.example.com") == "example.com"
    assert get_etld_plus_one("www.example.com") == "example.com"
    assert get_etld_plus_one("example.com") == "example.com"


def test_filter_pdp_candidate_urls_cross_subdomain_internal():
    """Cross-subdomain links (example.com -> www.example.com) accepted as internal."""
    base = "https://example.com/"
    urls = [
        "https://www.example.com/product/foo",
        "https://example.com/products/bar",
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    assert len(out) == 2
    assert "https://www.example.com/product/foo" in out
    assert "https://example.com/products/bar" in out


def test_filter_product_context_urls_cross_subdomain_internal():
    """Product-context filter accepts same-site subdomain links."""
    base = "https://www.foleja.com/"
    urls = [
        "https://foleja.com/categories/tv/MAR-200000509",
        "https://www.foleja.com/categories/tv/OTHER-SKU",
    ]
    out = filter_product_context_urls(urls, base, max_candidates=10)
    assert len(out) == 2
    assert "https://foleja.com/categories/tv/MAR-200000509" in out
    assert "https://www.foleja.com/categories/tv/OTHER-SKU" in out


def test_filter_pdp_candidate_urls_external_domain_excluded():
    """External domain links remain excluded (different eTLD+1)."""
    base = "https://example.com/"
    urls = [
        "https://example.com/product/ok",
        "https://other.com/product/ok",
        "https://evil.example.com/product/ok",
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    assert "https://example.com/product/ok" in out
    assert "https://other.com/product/ok" not in out
    # evil.example.com -> example.com (same eTLD+1 with heuristic)
    assert "https://evil.example.com/product/ok" in out


def test_filter_product_context_urls_external_domain_excluded():
    """Product-context filter still excludes external domains."""
    base = "https://example.com/"
    urls = [
        "https://example.com/categories/tv/SKU-1",
        "https://other.com/categories/tv/SKU-2",
    ]
    out = filter_product_context_urls(urls, base, max_candidates=10)
    assert "https://example.com/categories/tv/SKU-1" in out
    assert "https://other.com/categories/tv/SKU-2" not in out


# --- Category URLs with product-card style paths ---


def test_filter_product_context_urls_category_urls_with_sku_paths():
    """Category URLs with PDP links like /MAR-200000509/... are included (no path pattern)."""
    base = "https://example.com/"
    urls = [
        "https://example.com/MAR-200000509/",
        "https://example.com/categories/tv/MAR-200000509/",
        "https://example.com/shop/item/xyz-123",
    ]
    out = filter_product_context_urls(urls, base, max_candidates=10)
    assert len(out) == 3
    # Normalized URLs strip trailing slash
    assert "https://example.com/MAR-200000509" in out
    assert "https://example.com/categories/tv/MAR-200000509" in out
    assert "https://example.com/shop/item/xyz-123" in out


# --- Ordering and cap ---


def test_filter_pdp_candidate_urls_ordering_and_cap_after_dedupe():
    """Ordering preserved; cap enforced after dedupe."""
    base = "https://example.com/"
    urls = [
        "https://example.com/products/a",
        "https://example.com/products/a",  # duplicate
        "https://example.com/product/b",
        "https://example.com/products/c",
        "https://example.com/product/d",
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=3)
    assert len(out) == 3
    assert out[0] == "https://example.com/products/a"
    assert out[1] == "https://example.com/product/b"
    assert out[2] == "https://example.com/products/c"
    assert out == list(dict.fromkeys(out))  # no dupes


def test_filter_pdp_candidate_urls_dedupe_first_occurrence_wins():
    """Dedupe by normalized URL; first occurrence in input order is kept."""
    base = "https://example.com/"
    urls = [
        "https://example.com/product/first",
        "https://example.com/product/second",
        "https://example.com/product/first",  # duplicate, normalized same
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    assert len(out) == 2
    assert out[0] == "https://example.com/product/first"
    assert out[1] == "https://example.com/product/second"


def test_filter_pdp_candidate_urls_deterministic_ordering():
    """Same input produces same output order (stable ordering)."""
    base = "https://example.com/"
    urls = [
        "https://example.com/products/z",
        "https://example.com/product/a",
        "https://example.com/products/m",
    ]
    out1 = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    out2 = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    assert out1 == out2
    assert out1 == [
        "https://example.com/products/z",
        "https://example.com/product/a",
        "https://example.com/products/m",
    ]


def test_filter_pdp_candidate_urls_cap_enforced():
    """Result length never exceeds max_candidates."""
    base = "https://example.com/"
    urls = [f"https://example.com/product/{i}" for i in range(30)]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=5)
    assert len(out) == 5
    out2 = filter_pdp_candidate_urls(urls, base, max_candidates=1)
    assert len(out2) == 1


# --- Pattern-based selection still works ---


def test_filter_pdp_candidate_urls_pattern_based_still_works():
    """Existing pattern-based candidate selection still includes /product, /products, etc."""
    base = "https://example.com/"
    urls = [
        "https://example.com/product/foo",
        "https://example.com/products/bar",
        "https://example.com/p/123",
        "https://example.com/shop/widget",
        "https://example.com/collections/sale/products/item",
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    assert len(out) == 5
    assert "https://example.com/product/foo" in out
    assert "https://example.com/products/bar" in out
    assert "https://example.com/p/123" in out
    assert "https://example.com/shop/widget" in out
    assert "https://example.com/collections/sale/products/item" in out


# --- Deterministic ordering tests (spec requirement) ---


def test_filter_pdp_candidate_urls_stable_across_runs():
    """Same input produces identical output across multiple runs (determinism)."""
    base = "https://example.com/"
    urls = [
        "https://example.com/products/z",
        "https://example.com/product/a",
        "https://example.com/products/m",
        "https://example.com/product/b",
    ]

    # Run 10 times, should get identical results
    results = [filter_pdp_candidate_urls(urls, base, max_candidates=10) for _ in range(10)]

    # All results identical
    for result in results:
        assert result == results[0]

    # Order matches input order
    assert results[0] == urls


def test_filter_product_context_urls_stable_across_runs():
    """Product-context filter produces deterministic output."""
    base = "https://example.com/"
    urls = [
        "https://example.com/categories/z",
        "https://example.com/categories/a",
        "https://example.com/categories/m",
    ]

    results = [filter_product_context_urls(urls, base, max_candidates=10) for _ in range(10)]

    # All results identical
    for result in results:
        assert result == results[0]


def test_filter_pdp_candidate_urls_deterministic_with_duplicates():
    """Deduplication is deterministic (first occurrence wins)."""
    base = "https://example.com/"
    urls = [
        "https://example.com/product/first",
        "https://example.com/product/second",
        "https://example.com/product/first",  # duplicate
        "https://example.com/product/third",
        "https://example.com/product/second",  # duplicate
    ]

    # Multiple runs should produce identical order
    result1 = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    result2 = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    result3 = filter_pdp_candidate_urls(urls, base, max_candidates=10)

    assert result1 == result2 == result3
    assert result1 == [
        "https://example.com/product/first",
        "https://example.com/product/second",
        "https://example.com/product/third",
    ]


def test_filter_pdp_candidate_urls_cap_deterministic():
    """Capping produces deterministic results (first N by input order)."""
    base = "https://example.com/"
    urls = [f"https://example.com/product/{i}" for i in range(20)]

    result1 = filter_pdp_candidate_urls(urls, base, max_candidates=5)
    result2 = filter_pdp_candidate_urls(urls, base, max_candidates=5)

    assert result1 == result2
    assert len(result1) == 5
    # First 5 in input order
    assert result1 == [f"https://example.com/product/{i}" for i in range(5)]


# --- Query parameter and fragment handling ---


def test_filter_pdp_candidate_urls_strips_query_params():
    """URL normalization strips query parameters for consistency."""
    base = "https://example.com/"
    urls = [
        "https://example.com/product/foo?color=red",
        "https://example.com/products/bar?size=large",
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    # Normalized URLs without query params
    assert "https://example.com/product/foo" in out
    assert "https://example.com/products/bar" in out


def test_filter_pdp_candidate_urls_strips_fragments():
    """URL normalization strips fragments for consistency."""
    base = "https://example.com/"
    urls = [
        "https://example.com/product/foo#section1",
        "https://example.com/product/foo#section2",
        "https://example.com/product/foo",
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    # Should dedupe to single URL (fragments stripped)
    assert len(out) == 1
    assert out[0] == "https://example.com/product/foo"


def test_normalize_internal_url_strips_query_and_fragment():
    """Normalization removes query params and fragments for determinism."""
    base = "https://example.com/"
    assert (
        normalize_internal_url("/product/foo?q=1#section", base)
        == "https://example.com/product/foo"
    )
    assert (
        normalize_internal_url("/product/bar?color=red&size=xl", base)
        == "https://example.com/product/bar"
    )
    assert normalize_internal_url("/product/baz#top", base) == "https://example.com/product/baz"


# --- Edge cases ---


def test_filter_pdp_candidate_urls_empty_input():
    """Empty input returns empty list."""
    base = "https://example.com/"
    out = filter_pdp_candidate_urls([], base, max_candidates=10)
    assert out == []


def test_filter_product_context_urls_empty_input():
    """Product-context filter with empty input returns empty list."""
    base = "https://example.com/"
    out = filter_product_context_urls([], base, max_candidates=10)
    assert out == []


def test_filter_pdp_candidate_urls_all_filtered_out():
    """All URLs filtered out returns empty list."""
    base = "https://example.com/"
    urls = [
        "https://example.com/cart",
        "https://example.com/checkout",
        "https://example.com/account",
        "https://other.com/product/foo",  # external domain
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    assert out == []


def test_normalize_internal_url_strips_trailing_slash():
    """Trailing slashes are normalized consistently."""
    base = "https://example.com/"
    assert normalize_internal_url("/product/foo/", base) == "https://example.com/product/foo"
    assert normalize_internal_url("/product/foo", base) == "https://example.com/product/foo"


def test_filter_pdp_candidate_urls_case_insensitive_patterns():
    """PDP path patterns are case-insensitive."""
    base = "https://example.com/"
    urls = [
        "https://example.com/Product/foo",
        "https://example.com/PRODUCTS/bar",
        "https://example.com/P/123",
        "https://example.com/SHOP/widget",
    ]
    out = filter_pdp_candidate_urls(urls, base, max_candidates=10)
    assert len(out) == 4  # All should match


# --- extract_pdp_candidate_links (async; nav/footer exclusion) ---


@pytest.mark.asyncio
async def test_extract_pdp_candidate_links_nav_footer_excluded():
    """Links inside nav/footer are excluded from pattern pass; main content links included."""
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html>
    <html><body>
    <nav><a href="/product/nav-link">Nav</a></nav>
    <footer><a href="/product/footer-link">Footer</a></footer>
    <main><a href="/product/main-link">Main</a></main>
    </body></html>
    """
    base_url = "https://example.com/"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        result = await extract_pdp_candidate_links(page, base_url, max_candidates=20)
        await browser.close()
    main_url = "https://example.com/product/main-link"
    nav_url = "https://example.com/product/nav-link"
    footer_url = "https://example.com/product/footer-link"
    assert main_url in result
    assert nav_url not in result
    assert footer_url not in result
