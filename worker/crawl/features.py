"""
Feature extraction: homepage features JSON, PDP features, Product JSON-LD parsing.

Per TECH_SPEC_V1.md; no behavior change.
"""

from __future__ import annotations

import json
import re
from typing import Any

from playwright.async_api import Page

from worker.crawl.pdp_validation import PRICE_PATTERN
from worker.crawl.text import normalize_whitespace


async def extract_features_json(page: Page) -> dict:
    """
    Extract minimum features JSON for homepage.

    Includes: meta, headings, ctas, navigation, schema_org, review_signals.
    """
    features = {
        "meta": {},
        "headings": {"h1": [], "h2": []},
        "ctas": [],
        "navigation": {"main_nav_links": [], "footer_links": []},
        "schema_org": {"product_detected": False},
        "review_signals": {
            "review_count_present": False,
            "rating_value_present": False,
        },
    }

    # Meta
    title = await page.title()
    features["meta"]["title"] = title

    # Meta description (non-blocking; may be absent)
    try:
        meta_desc = await page.locator('meta[name="description"]').get_attribute(
            "content", timeout=1000
        )
    except Exception:
        meta_desc = None
    if meta_desc:
        features["meta"]["meta_description"] = meta_desc

    # Canonical link (non-blocking; may be absent)
    try:
        canonical = await page.locator('link[rel="canonical"]').get_attribute("href", timeout=1000)
    except Exception:
        canonical = None
    if canonical:
        features["meta"]["canonical_url"] = canonical

    # Headings
    h1_elements = await page.locator("h1").all()
    for h1 in h1_elements:
        text = await h1.inner_text()
        if text:
            features["headings"]["h1"].append(normalize_whitespace(text))

    h2_elements = await page.locator("h2").all()
    for h2 in h2_elements:
        text = await h2.inner_text()
        if text:
            features["headings"]["h2"].append(normalize_whitespace(text))

    # CTAs (simple heuristic: buttons/links with action words)
    cta_selectors = [
        'button:has-text("Buy")',
        'button:has-text("Add to Cart")',
        'a:has-text("Shop")',
        'a:has-text("Buy Now")',
        '[class*="cta"]',
        '[class*="button"]',
    ]
    for selector in cta_selectors:
        try:
            elements = await page.locator(selector).all()
            for elem in elements[:5]:  # Limit to first 5
                text = await elem.inner_text()
                href = await elem.get_attribute("href")
                if text:
                    features["ctas"].append(
                        {"text": normalize_whitespace(text), "href": href or ""}
                    )
        except Exception:
            continue

    # Navigation (simplified)
    nav_links = await page.locator("nav a, header a").all()
    for link in nav_links[:20]:  # Limit to first 20
        text = await link.inner_text()
        href = await link.get_attribute("href")
        if text and href:
            features["navigation"]["main_nav_links"].append(
                {"text": normalize_whitespace(text), "href": href}
            )

    footer_links = await page.locator("footer a").all()
    for link in footer_links[:20]:  # Limit to first 20
        text = await link.inner_text()
        href = await link.get_attribute("href")
        if text and href:
            features["navigation"]["footer_links"].append(
                {"text": normalize_whitespace(text), "href": href}
            )

    # Schema.org detection
    schema_scripts = await page.locator('script[type="application/ld+json"]').all()
    for script in schema_scripts:
        try:
            content = await script.inner_text()
            if '"@type"' in content and "Product" in content:
                features["schema_org"]["product_detected"] = True
                break
        except Exception:
            continue

    # Review signals (simple detection)
    review_indicators = await page.locator(
        '[class*="review"], [class*="rating"], [class*="star"]'
    ).count()
    if review_indicators > 0:
        features["review_signals"]["review_count_present"] = True
        features["review_signals"]["rating_value_present"] = True

    return features


def parse_product_ldjson(content: str) -> dict[str, Any]:
    """
    Parse Product schema.org JSON-LD and return product_fields (pure, for tests).

    Returns dict with name, sku, brand, offers, aggregateRating when present.
    """
    out: dict[str, Any] = {}
    try:
        data = json.loads(content)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    _extract_product_fields(item, out)
                    return out
            return out
        if isinstance(data, dict) and data.get("@type") == "Product":
            _extract_product_fields(data, out)
    except (json.JSONDecodeError, TypeError):
        pass
    return out


def _extract_product_fields(node: dict, out: dict[str, Any]) -> None:
    """Extract name, sku, brand, offers, aggregateRating from Product node."""
    if "name" in node:
        out["name"] = node["name"]
    if "sku" in node:
        out["sku"] = node["sku"]
    if "brand" in node:
        b = node["brand"]
        out["brand"] = b.get("name", b) if isinstance(b, dict) else b
    if "offers" in node:
        out["offers"] = node["offers"]
    if "aggregateRating" in node:
        out["aggregateRating"] = node["aggregateRating"]


async def extract_features_json_pdp(page: Page) -> dict:
    """
    Extract features JSON for PDP: common fields + pdp_core + schema_org product_fields.

    pdp_core: price, currency, availability, add_to_cart_present.
    schema_org: product_detected, product_fields when Product JSON-LD present.
    """
    features = await extract_features_json(page)

    # pdp_core (TECH_SPEC)
    features["pdp_core"] = {
        "price": None,
        "currency": None,
        "availability": None,
        "add_to_cart_present": False,
    }

    try:
        body_text = await page.inner_text("body", timeout=5000)
        price_match = PRICE_PATTERN.search(body_text)
        if price_match:
            features["pdp_core"]["price"] = price_match.group(0).strip()
        # Currency from common symbols or text
        if re.search(r"[\$]", body_text):
            features["pdp_core"]["currency"] = "USD"
        elif re.search(r"[£]", body_text):
            features["pdp_core"]["currency"] = "GBP"
        elif re.search(r"[€]", body_text):
            features["pdp_core"]["currency"] = "EUR"

        # Availability: in stock / out of stock heuristics
        body_lower = body_text.lower()
        if "in stock" in body_lower or "add to cart" in body_lower:
            features["pdp_core"]["availability"] = "in stock"
        elif "out of stock" in body_lower or "sold out" in body_lower:
            features["pdp_core"]["availability"] = "out of stock"

        add_selectors = [
            'button:has-text("Add to Cart")',
            'button:has-text("Add to Bag")',
            '[name="add-to-cart"]',
            '[class*="add-to-cart"]',
            '[class*="addToCart"]',
        ]
        for sel in add_selectors:
            if await page.locator(sel).first.count() > 0:
                features["pdp_core"]["add_to_cart_present"] = True
                break
    except Exception:
        pass

    # Schema.org Product: product_fields when detected
    features["schema_org"]["product_fields"] = {}
    schema_scripts = await page.locator('script[type="application/ld+json"]').all()
    for script in schema_scripts:
        try:
            content = await script.inner_text()
            if "Product" not in content or '"@type"' not in content:
                continue
            parsed = parse_product_ldjson(content)
            if parsed:
                features["schema_org"]["product_fields"] = parsed
                break
        except Exception:
            continue

    return features
