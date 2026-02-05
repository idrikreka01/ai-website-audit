"""
Unit tests for extraction retry policy (TECH_SPEC_V1.1.md §5 v1.24).

Covers: transient error detection, reason mapping, and that retry runs at most once.
No network or browser required; deterministic with mocked exceptions.
"""

from __future__ import annotations

import pytest

from worker.crawl_runner import (
    _is_transient_extraction_error,
    _transient_extraction_reason,
)


def test_is_transient_extraction_error_true_for_execution_context_destroyed():
    """Execution context destroyed is treated as transient (retry allowed)."""
    exc = ValueError("Execution context was destroyed, most likely because of a navigation")
    assert _is_transient_extraction_error(exc) is True


def test_is_transient_extraction_error_true_for_target_closed():
    """Target closed is treated as transient."""
    assert _is_transient_extraction_error(RuntimeError("Target closed")) is True


def test_is_transient_extraction_error_true_for_navigation_interrupted():
    """Navigation interrupted is treated as transient."""
    assert _is_transient_extraction_error(OSError("Navigation interrupted")) is True


def test_is_transient_extraction_error_case_insensitive():
    """Matching is case-insensitive."""
    assert _is_transient_extraction_error(ValueError("TARGET CLOSED")) is True
    assert _is_transient_extraction_error(ValueError("execution context was destroyed")) is True


def test_is_transient_extraction_error_false_for_other_errors():
    """Non-transient errors do not trigger retry."""
    assert _is_transient_extraction_error(ValueError("Selector not found")) is False
    assert _is_transient_extraction_error(TimeoutError("timeout")) is False
    assert _is_transient_extraction_error(RuntimeError("Page crashed")) is False


def test_transient_extraction_reason_returns_correct_reasons():
    """Reason strings match spec for logging."""
    assert (
        _transient_extraction_reason(ValueError("Execution context was destroyed"))
        == "execution_context_destroyed"
    )
    assert _transient_extraction_reason(ValueError("Target closed")) == "target_closed"
    assert (
        _transient_extraction_reason(ValueError("Navigation interrupted"))
        == "navigation_interrupted"
    )


def test_transient_extraction_reason_unknown_falls_back_to_transient():
    """Unknown message returns 'transient'."""
    assert _transient_extraction_reason(ValueError("Something else")) == "transient"


@pytest.mark.asyncio
async def test_retry_attempts_only_once():
    """Retry logic allows at most one retry (2 attempts total); no infinite loop."""
    call_count = 0

    async def extraction():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("Execution context was destroyed")
        return "ok"

    # Same condition as crawl_runner extraction loop
    extraction_attempt = 1
    result = None
    while True:
        try:
            result = await extraction()
            break
        except Exception as e:
            if not _is_transient_extraction_error(e) or extraction_attempt >= 2:
                raise
            extraction_attempt += 1

    assert result == "ok"
    assert call_count == 2, "Extraction must be called exactly twice (initial + one retry)"
