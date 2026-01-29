"""
Text normalization for crawl (whitespace collapse, trim).

Per TECH_SPEC_V1.md; no behavior change.
"""

from __future__ import annotations

import re


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace: collapse multiples, trim."""
    # Collapse multiple whitespace to single space
    text = re.sub(r"\s+", " ", text)
    # Trim
    text = text.strip()
    return text
