"""
Unit tests for pre-consent vendor scripts and mapping.
"""

from __future__ import annotations

from worker.crawl.consent import (
    DEFAULT_VENDORS,
    VENDOR_CIVIC,
    VENDOR_COMPLIANZ,
    VENDOR_COOKIEBOT,
    VENDOR_DIDOMI,
    VENDOR_IUBENDA,
    VENDOR_ONETRUST,
    VENDOR_OSANO,
    VENDOR_QUANTCAST,
    VENDOR_SHOPWARE,
    VENDOR_TRUSTARC,
    VENDOR_USERCENTRICS,
    get_preconsent_scripts,
)


def test_default_vendors_include_onetrust_and_shopware():
    assert VENDOR_ONETRUST in DEFAULT_VENDORS
    assert VENDOR_SHOPWARE in DEFAULT_VENDORS
    assert VENDOR_COOKIEBOT in DEFAULT_VENDORS
    assert VENDOR_TRUSTARC in DEFAULT_VENDORS
    assert VENDOR_QUANTCAST in DEFAULT_VENDORS
    assert VENDOR_DIDOMI in DEFAULT_VENDORS
    assert VENDOR_USERCENTRICS in DEFAULT_VENDORS
    assert VENDOR_COMPLIANZ in DEFAULT_VENDORS
    assert VENDOR_CIVIC in DEFAULT_VENDORS
    assert VENDOR_OSANO in DEFAULT_VENDORS
    assert VENDOR_IUBENDA in DEFAULT_VENDORS


def test_get_preconsent_scripts_returns_non_empty_scripts():
    scripts = get_preconsent_scripts(DEFAULT_VENDORS)
    assert len(scripts) >= 2
    for vendor, script in scripts:
        assert isinstance(vendor, str) and vendor
        assert isinstance(script, str) and script.strip()


def test_get_preconsent_scripts_ignores_unknown_vendor():
    scripts = get_preconsent_scripts(["unknown_vendor"])
    assert scripts == []
