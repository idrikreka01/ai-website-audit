"""
PDP validation: base (price + title+image) plus strong signal (add-to-cart or product schema).

Per TECH_SPEC_V1.1.md §3: valid PDP = (price + title+image) and (add-to-cart OR schema).
"""

from __future__ import annotations

import re

from playwright.async_api import Page

# Price: currency + numeric pattern
PRICE_PATTERN = re.compile(
    r"[\$£€]\s*\d+(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?\s*[\$£€]|\b\d+(?:[.,]\d+)?\s*(?:usd|eur|gbp)\b",
    re.I,
)


def evaluate_pdp_validation_signals(
    *,
    has_price: bool,
    has_add_to_cart: bool,
    has_product_schema: bool,
    has_title_and_image: bool,
) -> tuple[bool, bool, bool]:
    """
    Evaluate PDP validation rule (pure function for tests).

    Valid PDP requires: (price + title+image) and (add-to-cart OR product schema).
    Returns (is_valid: bool, base_met: bool, strong_signal_met: bool).
    """
    base_met = has_price and has_title_and_image
    strong_signal_met = has_add_to_cart or has_product_schema
    is_valid = base_met and strong_signal_met
    return (is_valid, base_met, strong_signal_met)


def is_valid_pdp_page(signals: dict) -> bool:
    """
    Return True if signals dict indicates a valid PDP.

    Rule: (price + title+image) and (add-to-cart OR product schema).
    Pure function for tests. signals keys: has_price, has_add_to_cart,
    has_product_schema, has_title_and_image.
    """
    valid, _, _ = evaluate_pdp_validation_signals(
        has_price=bool(signals.get("has_price")),
        has_add_to_cart=bool(signals.get("has_add_to_cart")),
        has_product_schema=bool(signals.get("has_product_schema")),
        has_title_and_image=bool(signals.get("has_title_and_image")),
    )
    return valid


async def extract_pdp_validation_signals(page: Page) -> dict:
    """
    Extract PDP validation signals from current page: price, add-to-cart,
    product schema, title+image.

    Returns dict with boolean keys: has_price, has_add_to_cart,
    has_product_schema, has_title_and_image.
    """
    signals = {
        "has_price": False,
        "has_add_to_cart": False,
        "has_product_schema": False,
        "has_title_and_image": False,
    }
    try:
        # Price: body text or common price selectors
        body_text = await page.inner_text("body", timeout=5000)
        signals["has_price"] = bool(PRICE_PATTERN.search(body_text))
        if not signals["has_price"]:
            price_el = (
                await page.locator(
                    "[class*='price'], [data-price], [itemprop='price']"
                ).first.count()
                > 0
            )
            signals["has_price"] = price_el

        # Add-to-cart / buy button
        add_selectors = [
            'button:has-text("Add to Cart")',
            'button:has-text("Add to Bag")',
            'button:has-text("Buy Now")',
            '[name="add-to-cart"]',
            '[class*="add-to-cart"]',
            '[class*="addToCart"]',
        ]
        for sel in add_selectors:
            if await page.locator(sel).first.count() > 0:
                signals["has_add_to_cart"] = True
                break

        # Product schema.org JSON-LD
        scripts = await page.locator('script[type="application/ld+json"]').all()
        for script in scripts:
            try:
                content = await script.inner_text()
                if '"@type"' in content and "Product" in content:
                    signals["has_product_schema"] = True
                    break
            except Exception:
                continue

        # Product title + image cluster (h1 or product title + at least one img)
        has_h1 = await page.locator("h1").first.count() > 0
        product_title = (
            await page.locator(
                "[class*='product-title'], [class*='product_title'], [itemprop='name']"
            ).first.count()
            > 0
        )
        has_img = await page.locator("img").first.count() > 0
        signals["has_title_and_image"] = (has_h1 or product_title) and has_img
    except Exception:
        pass
    return signals
