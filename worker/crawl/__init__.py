"""
Playwright-based crawling helpers for homepage evidence capture.

This package implements the page-ready rules, scrolling, popup dismissal,
and artifact extraction per TECH_SPEC_V1.md.

Public API: re-exports all symbols used by jobs.py and tests so that
`from worker.crawl import ...` remains valid.
"""

from __future__ import annotations

from worker.crawl.browser import create_browser_context
from worker.crawl.constants import (
    DOM_STABILITY_TIMEOUT,
    EXCLUDED_PATH_SEGMENTS,
    HARD_TIMEOUT_MS,
    MAX_PDP_CANDIDATES,
    MINIMUM_WAIT_AFTER_LOAD,
    NETWORK_IDLE_TIMEOUT,
    PDP_PATH_PATTERNS,
    PRODUCT_LIKE_CONTAINER_SELECTORS,
    SCROLL_WAIT,
    VIEWPORT_CONFIGS,
    Viewport,
)
from worker.crawl.features import (
    _extract_product_fields,
    extract_features_json,
    extract_features_json_pdp,
    parse_product_ldjson,
)
from worker.crawl.navigation_retry import (
    NavigateResult,
    is_bot_block_page,
    navigate_with_retry,
)
from worker.crawl.pdp_candidates import (
    _path_has_excluded_segment,
    extract_pdp_candidate_links,
    filter_pdp_candidate_urls,
    filter_product_context_urls,
    get_etld_plus_one,
    is_pdp_candidate_path,
    normalize_internal_url,
)
from worker.crawl.pdp_validation import (
    PRICE_PATTERN,
    evaluate_pdp_validation_signals,
    extract_pdp_validation_signals,
    is_valid_pdp_page,
)
from worker.crawl.readiness import dismiss_popups, scroll_sequence, wait_for_page_ready
from worker.crawl.text import normalize_whitespace

__all__ = [
    # constants
    "Viewport",
    "VIEWPORT_CONFIGS",
    "NETWORK_IDLE_TIMEOUT",
    "DOM_STABILITY_TIMEOUT",
    "MINIMUM_WAIT_AFTER_LOAD",
    "HARD_TIMEOUT_MS",
    "SCROLL_WAIT",
    "EXCLUDED_PATH_SEGMENTS",
    "MAX_PDP_CANDIDATES",
    "PDP_PATH_PATTERNS",
    "PRODUCT_LIKE_CONTAINER_SELECTORS",
    # browser
    "create_browser_context",
    # navigation_retry
    "NavigateResult",
    "navigate_with_retry",
    "is_bot_block_page",
    # readiness
    "wait_for_page_ready",
    "scroll_sequence",
    "dismiss_popups",
    # text
    "normalize_whitespace",
    # pdp_candidates
    "is_pdp_candidate_path",
    "_path_has_excluded_segment",
    "get_etld_plus_one",
    "normalize_internal_url",
    "filter_pdp_candidate_urls",
    "filter_product_context_urls",
    "extract_pdp_candidate_links",
    # pdp_validation
    "PRICE_PATTERN",
    "evaluate_pdp_validation_signals",
    "is_valid_pdp_page",
    "extract_pdp_validation_signals",
    # features
    "extract_features_json",
    "parse_product_ldjson",
    "_extract_product_fields",
    "extract_features_json_pdp",
]
