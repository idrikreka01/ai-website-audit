"""
Crawl constants: viewport configs, timeouts, PDP patterns, excluded segments.

Per TECH_SPEC_V1.md; no behavior change.
"""

from __future__ import annotations

from typing import Literal

Viewport = Literal["desktop", "mobile"]

# Viewport configurations
VIEWPORT_CONFIGS = {
    "desktop": {"width": 1920, "height": 1080},
    "mobile": {"width": 375, "height": 667},
}

# Timeout constants (in milliseconds)
NETWORK_IDLE_TIMEOUT = 800  # Network idle window
DOM_STABILITY_TIMEOUT = 1000  # DOM stability window
MINIMUM_WAIT_AFTER_LOAD = 500  # Minimum wait after load
HARD_TIMEOUT_MS = 30000  # Hard timeout cap per page
SCROLL_WAIT = 500  # Wait after each scroll

# URL path patterns for PDP candidates (case-insensitive); match path segment or full path
PDP_PATH_PATTERNS = [
    r"/product(?:s)?/",  # /product/, /products/
    r"/p/",
    r"/item(?:s)?/",
    r"/collections/[^/]+/products/",  # Shopify
    r"/products/",  # Shopify
    r"/shop/",  # common
]
# Paths to exclude (account, cart, checkout, logout)
EXCLUDED_PATH_SEGMENTS = {"account", "cart", "checkout", "logout", "login", "signin", "signout"}

# Max PDP candidates to validate (deterministic cap)
MAX_PDP_CANDIDATES = 20

# Container element selectors (product-like boxes). Links inside are candidates when
# the container has at least PRODUCT_CONTAINER_MIN_SIGNALS of: price, title, image, add-to-cart.
PRODUCT_CONTAINER_SELECTORS = [
    ".product",
    "[class*='product-box']",
    "[class*='product-card']",
    "[class*='product-item']",
    ".card",
    "[class*='theProduct']",
    "[data-product-id]",
    "[data-product]",
]

# Legacy: broad "container a[href]" selectors for pattern-free candidate collection.
# Context pass uses PRODUCT_CONTAINER_SELECTORS + 2-of-4 signal check instead.
PRODUCT_LIKE_CONTAINER_SELECTORS = [
    ".product a[href]",
    "[class*='product-box'] a[href]",
    "[class*='product-card'] a[href]",
    "[class*='product-item'] a[href]",
    ".card a[href]",
    "[class*='theProduct'] a[href]",
    "[data-product-id] a[href]",
    "[data-product] a[href]",
]

# Minimum signals (2-of-4) required inside a product-like container to accept its links.
PRODUCT_CONTAINER_MIN_SIGNALS = 2

# Selectors for container signal detection (price, title, image, add-to-cart).
# Used when evaluating product-like containers; at least MIN_SIGNALS must match.
PRODUCT_CONTAINER_PRICE_SELECTORS = [
    "[class*='price'], [data-price], [itemprop='price']",
]
PRODUCT_CONTAINER_TITLE_SELECTORS = [
    "h1, h2, h3, [class*='product-name'], [class*='product_title'], [itemprop='name']",
]
PRODUCT_CONTAINER_IMAGE_SELECTOR = "img"
PRODUCT_CONTAINER_ADD_TO_CART_SELECTORS = [
    "[class*='add-to-cart'], [class*='addToCart'], [name='add-to-cart']",
    "button:has-text('Add to Cart'), button:has-text('Add to Bag'), button:has-text('Buy Now')",
    "[class*='cart']",
]
