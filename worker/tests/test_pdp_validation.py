"""
Unit tests for PDP validation signal evaluation (2-of-4 rule, pure functions).
"""

from __future__ import annotations

from worker.crawl import (
    evaluate_pdp_validation_signals,
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
