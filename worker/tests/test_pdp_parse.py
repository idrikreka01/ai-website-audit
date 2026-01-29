"""
Unit tests for PDP parsing helpers (parse_product_ldjson, pure functions).
"""

from __future__ import annotations

from worker.crawl import parse_product_ldjson


def test_parse_product_ldjson_single_product():
    content = '{"@type": "Product", "name": "Widget", "sku": "W1"}'
    out = parse_product_ldjson(content)
    assert out.get("name") == "Widget"
    assert out.get("sku") == "W1"


def test_parse_product_ldjson_with_brand():
    content = '{"@type": "Product", "name": "Thing", "brand": {"@type": "Brand", "name": "Acme"}}'
    out = parse_product_ldjson(content)
    assert out.get("name") == "Thing"
    assert out.get("brand") == "Acme"


def test_parse_product_ldjson_array():
    content = '[{"@type": "Organization"}, {"@type": "Product", "name": "Item"}]'
    out = parse_product_ldjson(content)
    assert out.get("name") == "Item"


def test_parse_product_ldjson_no_product():
    content = '{"@type": "WebPage", "name": "Home"}'
    out = parse_product_ldjson(content)
    assert out == {}


def test_parse_product_ldjson_invalid_json():
    out = parse_product_ldjson("not json")
    assert out == {}
