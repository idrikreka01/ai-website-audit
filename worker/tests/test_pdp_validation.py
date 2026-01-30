"""
Unit tests for PDP validation: 2-of-4 rule, signal evaluation, and signal extraction.

Covers: price detection (regex + selector fallback), add-to-cart selectors,
schema.org detection, title+image detection. No change to validation rule.
"""

from __future__ import annotations

import pytest

from worker.crawl import (
    PRICE_PATTERN,
    evaluate_pdp_validation_signals,
    extract_pdp_validation_signals,
    is_valid_pdp_page,
)


def test_evaluate_pdp_validation_signals_two_met():
    valid, count = evaluate_pdp_validation_signals(
        has_price=True,
        has_add_to_cart=True,
        has_product_schema=False,
        has_title_and_image=False,
    )
    assert valid is True
    assert count == 2


def test_evaluate_pdp_validation_signals_three_met():
    valid, count = evaluate_pdp_validation_signals(
        has_price=True,
        has_add_to_cart=True,
        has_product_schema=True,
        has_title_and_image=False,
    )
    assert valid is True
    assert count == 3


def test_evaluate_pdp_validation_signals_one_met():
    valid, count = evaluate_pdp_validation_signals(
        has_price=True,
        has_add_to_cart=False,
        has_product_schema=False,
        has_title_and_image=False,
    )
    assert valid is False
    assert count == 1


def test_evaluate_pdp_validation_signals_zero_met():
    valid, count = evaluate_pdp_validation_signals(
        has_price=False,
        has_add_to_cart=False,
        has_product_schema=False,
        has_title_and_image=False,
    )
    assert valid is False
    assert count == 0


def test_evaluate_pdp_validation_signals_four_met():
    valid, count = evaluate_pdp_validation_signals(
        has_price=True,
        has_add_to_cart=True,
        has_product_schema=True,
        has_title_and_image=True,
    )
    assert valid is True
    assert count == 4


def test_is_valid_pdp_page_dict():
    assert (
        is_valid_pdp_page(
            {
                "has_price": True,
                "has_add_to_cart": True,
                "has_product_schema": False,
                "has_title_and_image": False,
            }
        )
        is True
    )
    assert (
        is_valid_pdp_page(
            {
                "has_price": True,
                "has_add_to_cart": False,
                "has_product_schema": False,
                "has_title_and_image": False,
            }
        )
        is False
    )
    assert (
        is_valid_pdp_page(
            {
                "has_price": False,
                "has_add_to_cart": False,
                "has_product_schema": True,
                "has_title_and_image": True,
            }
        )
        is True
    )


def test_is_valid_pdp_page_missing_keys_treated_false():
    assert is_valid_pdp_page({}) is False
    assert is_valid_pdp_page({"has_price": True}) is False


# --- Price detection: regex (PRICE_PATTERN) ---


def test_price_pattern_matches_dollar():
    """Price regex matches $ prefix and suffix."""
    assert PRICE_PATTERN.search("Price: $10.99") is not None
    assert PRICE_PATTERN.search("$99") is not None
    assert PRICE_PATTERN.search("100 $") is not None


def test_price_pattern_matches_pound_euro():
    """Price regex matches £ and €."""
    assert PRICE_PATTERN.search("£5.00") is not None
    assert PRICE_PATTERN.search("€19,99") is not None


def test_price_pattern_matches_currency_words():
    """Price regex matches USD, EUR, GBP."""
    assert PRICE_PATTERN.search("42.50 USD") is not None
    assert PRICE_PATTERN.search("10 eur") is not None
    assert PRICE_PATTERN.search("7.99 GBP") is not None


def test_price_pattern_no_match():
    """Price regex does not match plain text without currency."""
    assert PRICE_PATTERN.search("no price here") is None
    assert PRICE_PATTERN.search("Quantity: 5") is None


# --- Signal extraction (async; requires page) ---


@pytest.mark.asyncio
async def test_extract_signals_price_via_regex():
    """Price detected from body text via PRICE_PATTERN."""
    from playwright.async_api import async_playwright

    html = """<!DOCTYPE html><html><body><p>Product $29.99</p></body></html>"""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        signals = await extract_pdp_validation_signals(page)
        await browser.close()
    assert signals["has_price"] is True


@pytest.mark.asyncio
async def test_extract_signals_price_via_selector_fallback():
    """Price detected via selector when body text has no regex match."""
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><body>
    <p>No currency in text</p>
    <span class="product-price">x</span>
    </body></html>
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        signals = await extract_pdp_validation_signals(page)
        await browser.close()
    assert signals["has_price"] is True


@pytest.mark.asyncio
async def test_extract_signals_price_via_data_price():
    """Price detected via [data-price] selector fallback."""
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><body>
    <span data-price="19.99">19.99</span>
    </body></html>
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        signals = await extract_pdp_validation_signals(page)
        await browser.close()
    assert signals["has_price"] is True


@pytest.mark.asyncio
async def test_extract_signals_add_to_cart_button_text():
    """Add-to-cart detected via button text selectors."""
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><body>
    <button>Add to Cart</button>
    </body></html>
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        signals = await extract_pdp_validation_signals(page)
        await browser.close()
    assert signals["has_add_to_cart"] is True


@pytest.mark.asyncio
async def test_extract_signals_add_to_cart_name_attribute():
    """Add-to-cart detected via [name="add-to-cart"]."""
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><body>
    <input type="submit" name="add-to-cart" value="Add" />
    </body></html>
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        signals = await extract_pdp_validation_signals(page)
        await browser.close()
    assert signals["has_add_to_cart"] is True


@pytest.mark.asyncio
async def test_extract_signals_add_to_cart_class():
    """Add-to-cart detected via class addToCart."""
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><body>
    <button class="btn addToCart">Add</button>
    </body></html>
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        signals = await extract_pdp_validation_signals(page)
        await browser.close()
    assert signals["has_add_to_cart"] is True


@pytest.mark.asyncio
async def test_extract_signals_schema_org_product():
    """Product schema.org JSON-LD sets has_product_schema."""
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><head>
    <script type="application/ld+json">
    {"@type": "Product", "name": "Widget", "sku": "123"}
    </script>
    </head><body></body></html>
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        signals = await extract_pdp_validation_signals(page)
        await browser.close()
    assert signals["has_product_schema"] is True


@pytest.mark.asyncio
async def test_extract_signals_schema_org_no_product():
    """Non-Product JSON-LD does not set has_product_schema."""
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><head>
    <script type="application/ld+json">
    {"@type": "WebPage", "name": "Home"}
    </script>
    </head><body></body></html>
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        signals = await extract_pdp_validation_signals(page)
        await browser.close()
    assert signals["has_product_schema"] is False


@pytest.mark.asyncio
async def test_extract_signals_title_and_image_h1_and_img():
    """Title+image detected when h1 and img present."""
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><body>
    <h1>Product Name</h1>
    <img src="product.jpg" alt="Product" />
    </body></html>
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        signals = await extract_pdp_validation_signals(page)
        await browser.close()
    assert signals["has_title_and_image"] is True


@pytest.mark.asyncio
async def test_extract_signals_title_and_image_product_title_selector():
    """Title+image detected via product-title class and img."""
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><body>
    <span class="product-title">Widget</span>
    <img src="w.jpg" alt="W" />
    </body></html>
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        signals = await extract_pdp_validation_signals(page)
        await browser.close()
    assert signals["has_title_and_image"] is True


@pytest.mark.asyncio
async def test_extract_signals_title_and_image_fails_without_image():
    """Title+image is False when no img present."""
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><body>
    <h1>Product Name</h1>
    </body></html>
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        signals = await extract_pdp_validation_signals(page)
        await browser.close()
    assert signals["has_title_and_image"] is False


@pytest.mark.asyncio
async def test_extract_signals_title_and_image_fails_without_title():
    """Title+image is False when no h1 or product title."""
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><body>
    <img src="x.jpg" alt="X" />
    </body></html>
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        signals = await extract_pdp_validation_signals(page)
        await browser.close()
    assert signals["has_title_and_image"] is False


# --- Validation rule edge cases (2-of-4) ---


def test_evaluate_pdp_validation_signals_all_combinations():
    """Test all 16 combinations of 4 signals for 2-of-4 rule."""
    signals = [
        (False, False, False, False),  # 0 met -> invalid
        (True, False, False, False),  # 1 met -> invalid
        (False, True, False, False),  # 1 met -> invalid
        (False, False, True, False),  # 1 met -> invalid
        (False, False, False, True),  # 1 met -> invalid
        (True, True, False, False),  # 2 met -> valid
        (True, False, True, False),  # 2 met -> valid
        (True, False, False, True),  # 2 met -> valid
        (False, True, True, False),  # 2 met -> valid
        (False, True, False, True),  # 2 met -> valid
        (False, False, True, True),  # 2 met -> valid
        (True, True, True, False),  # 3 met -> valid
        (True, True, False, True),  # 3 met -> valid
        (True, False, True, True),  # 3 met -> valid
        (False, True, True, True),  # 3 met -> valid
        (True, True, True, True),  # 4 met -> valid
    ]

    expected_valid = [
        False,
        False,
        False,
        False,
        False,  # 0-1 met
        True,
        True,
        True,
        True,
        True,
        True,  # 2 met
        True,
        True,
        True,
        True,  # 3 met
        True,  # 4 met
    ]

    for i, (price, cart, schema, title_img) in enumerate(signals):
        valid, count = evaluate_pdp_validation_signals(
            has_price=price,
            has_add_to_cart=cart,
            has_product_schema=schema,
            has_title_and_image=title_img,
        )
        assert valid == expected_valid[i], f"Failed at index {i}: {signals[i]}"
        assert count == sum([price, cart, schema, title_img])


def test_evaluate_pdp_validation_signals_boundary():
    """Test 2-of-4 rule boundary: exactly 2 met is valid, 1 is not."""
    # Exactly 1 signal met (boundary below threshold)
    valid_1, count_1 = evaluate_pdp_validation_signals(
        has_price=True,
        has_add_to_cart=False,
        has_product_schema=False,
        has_title_and_image=False,
    )
    assert valid_1 is False
    assert count_1 == 1

    # Exactly 2 signals met (boundary at threshold)
    valid_2, count_2 = evaluate_pdp_validation_signals(
        has_price=True,
        has_add_to_cart=True,
        has_product_schema=False,
        has_title_and_image=False,
    )
    assert valid_2 is True
    assert count_2 == 2


def test_is_valid_pdp_page_all_signal_combinations():
    """Test is_valid_pdp_page wrapper with various signal dicts."""
    # Valid: 2 signals
    assert (
        is_valid_pdp_page(
            {
                "has_price": True,
                "has_add_to_cart": True,
                "has_product_schema": False,
                "has_title_and_image": False,
            }
        )
        is True
    )

    # Valid: 3 signals
    assert (
        is_valid_pdp_page(
            {
                "has_price": True,
                "has_add_to_cart": False,
                "has_product_schema": True,
                "has_title_and_image": True,
            }
        )
        is True
    )

    # Invalid: 1 signal
    assert (
        is_valid_pdp_page(
            {
                "has_price": False,
                "has_add_to_cart": False,
                "has_product_schema": False,
                "has_title_and_image": True,
            }
        )
        is False
    )

    # Invalid: 0 signals
    assert (
        is_valid_pdp_page(
            {
                "has_price": False,
                "has_add_to_cart": False,
                "has_product_schema": False,
                "has_title_and_image": False,
            }
        )
        is False
    )


# --- Price pattern edge cases ---


def test_price_pattern_decimal_separator_variations():
    """Price pattern matches both comma and dot decimal separators."""
    assert PRICE_PATTERN.search("$10.99") is not None
    assert PRICE_PATTERN.search("€19,99") is not None
    assert PRICE_PATTERN.search("£5.00") is not None


def test_price_pattern_no_decimal():
    """Price pattern matches whole numbers."""
    assert PRICE_PATTERN.search("$99") is not None
    assert PRICE_PATTERN.search("€100") is not None


def test_price_pattern_currency_position():
    """Price pattern matches currency before or after number."""
    assert PRICE_PATTERN.search("$29.99") is not None  # Before
    assert PRICE_PATTERN.search("29.99 USD") is not None  # After


def test_price_pattern_whitespace_variations():
    """Price pattern handles various whitespace."""
    assert PRICE_PATTERN.search("Price:$10.99") is not None
    assert PRICE_PATTERN.search("Price: $10.99") is not None
    assert PRICE_PATTERN.search("Price:  $10.99") is not None


# --- Signal extraction determinism ---


@pytest.mark.asyncio
async def test_extract_signals_deterministic():
    """Signal extraction produces consistent results across runs."""
    from playwright.async_api import async_playwright

    html = """
    <!DOCTYPE html><html><body>
    <h1>Product Name</h1>
    <p>Price: $29.99</p>
    <button>Add to Cart</button>
    <img src="product.jpg" alt="Product" />
    <script type="application/ld+json">
    {"@type": "Product", "name": "Widget"}
    </script>
    </body></html>
    """

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")

        # Extract signals multiple times
        signals1 = await extract_pdp_validation_signals(page)
        signals2 = await extract_pdp_validation_signals(page)
        signals3 = await extract_pdp_validation_signals(page)

        await browser.close()

    # All runs produce identical results
    assert signals1 == signals2 == signals3
    assert signals1["has_price"] is True
    assert signals1["has_add_to_cart"] is True
    assert signals1["has_product_schema"] is True
    assert signals1["has_title_and_image"] is True


@pytest.mark.asyncio
async def test_extract_signals_all_false():
    """Signal extraction with no matching elements returns all False."""
    from playwright.async_api import async_playwright

    html = """<!DOCTYPE html><html><body><p>Empty page</p></body></html>"""

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html, wait_until="domcontentloaded")
        signals = await extract_pdp_validation_signals(page)
        await browser.close()

    assert signals["has_price"] is False
    assert signals["has_add_to_cart"] is False
    assert signals["has_product_schema"] is False
    assert signals["has_title_and_image"] is False
