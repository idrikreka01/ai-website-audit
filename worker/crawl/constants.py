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

# Product-like container selectors: anchors inside these are candidates without URL pattern.
# Class hints and data-* product attributes for sites that don't use /product-style URLs.
PRODUCT_LIKE_CONTAINER_SELECTORS = [
    "[class*='product'] a[href]",
    "[class*='product-item'] a[href]",
    "[class*='product-card'] a[href]",
    "[class*='theProduct'] a[href]",
    "[data-product-id] a[href]",
    "[data-product] a[href]",
]
