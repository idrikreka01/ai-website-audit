"""
Unit tests for PDP candidate link filtering and normalization (pure functions).
"""

from __future__ import annotations

from worker.crawl import (
    filter_pdp_candidate_urls,
    filter_product_context_urls,
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
