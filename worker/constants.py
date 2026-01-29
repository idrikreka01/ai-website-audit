"""
Worker-level constants for job flow: viewport lists for homepage and PDP.

Used by crawl_runner and pdp_discovery; no behavior change.
"""

from __future__ import annotations

# Homepage viewports (page_type, viewport)
HOMEPAGE_VIEWPORTS = [
    ("homepage", "desktop"),
    ("homepage", "mobile"),
]

# PDP page types (desktop + mobile); evidence captured when pdp_url is set (Task 08)
PDP_VIEWPORTS = [
    ("pdp", "desktop"),
    ("pdp", "mobile"),
]
