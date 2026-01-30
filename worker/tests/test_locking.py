"""
Unit tests for Redis domain lock and throttle helpers (TECH_SPEC_V1.1.md).

Uses mocked Redis; no real Redis required. Covers acquire/release, throttle delay, retry backoff.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from worker.constants import LOCK_KEY_PREFIX, THROTTLE_KEY_PREFIX
from worker.locking import (
    DomainLockTimeoutError,
    acquire_domain_lock,
    normalize_domain,
    release_domain_lock,
    throttle_wait,
    update_throttle_after_session,
)


def _lock_config(
    ttl_seconds: int = 300,
    max_retries: int = 3,
    backoff_base_ms: int = 1000,
    min_delay_ms: int = 2000,
    throttle_ttl_seconds: int = 60,
    disable_throttle: bool = False,
    disable_locks: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        domain_lock_ttl_seconds=ttl_seconds,
        domain_lock_max_retries=max_retries,
        domain_lock_backoff_base_ms=backoff_base_ms,
        domain_min_delay_ms=min_delay_ms,
        domain_throttle_ttl_seconds=throttle_ttl_seconds,
        disable_throttle=disable_throttle,
        disable_locks=disable_locks,
    )


# --- normalize_domain ---


def test_normalize_domain_url_strips_protocol_and_www():
    assert normalize_domain("https://www.example.com/path") == "example.com"
    assert normalize_domain("https://example.com/") == "example.com"


def test_normalize_domain_lowercase():
    assert normalize_domain("HTTPS://WWW.EXAMPLE.COM") == "example.com"


def test_normalize_domain_netloc_only():
    assert normalize_domain("example.com") == "example.com"
    assert normalize_domain("www.example.com") == "example.com"


# --- acquire_domain_lock ---


def test_acquire_domain_lock_success_when_key_not_set():
    redis = MagicMock()
    redis.set.return_value = True
    config = _lock_config()

    acquire_domain_lock(redis, "example.com", "worker-1", "sess-123", config)

    redis.set.assert_called_once()
    call_kw = redis.set.call_args[1]
    assert call_kw.get("nx") is True
    assert call_kw.get("ex") == 300
    assert "worker-1:sess-123:" in redis.set.call_args[0][1]


def test_acquire_domain_lock_uses_correct_key_prefix():
    redis = MagicMock()
    redis.set.return_value = True
    config = _lock_config()

    acquire_domain_lock(redis, "example.com", "w", "s", config)

    key = redis.set.call_args[0][0]
    assert key == f"{LOCK_KEY_PREFIX}example.com"


def test_acquire_domain_lock_timeout_after_max_retries():
    redis = MagicMock()
    redis.set.return_value = False
    config = _lock_config(max_retries=3)

    with patch("worker.locking.time.sleep") as mock_sleep:
        with pytest.raises(DomainLockTimeoutError) as exc_info:
            acquire_domain_lock(redis, "example.com", "w", "s", config)

    assert "Domain lock timeout" in str(exc_info.value)
    assert redis.set.call_count == 3
    mock_sleep.assert_called()
    calls = [c[0][0] for c in mock_sleep.call_args_list]
    assert len(calls) == 2
    assert 1.0 <= calls[0] <= 1.5
    assert 2.0 <= calls[1] <= 2.5


def test_acquire_domain_lock_succeeds_on_second_attempt():
    redis = MagicMock()
    redis.set.side_effect = [False, True]
    config = _lock_config(max_retries=3)

    with patch("worker.locking.time.sleep"):
        acquire_domain_lock(redis, "example.com", "w", "s", config)

    assert redis.set.call_count == 2


# --- release_domain_lock ---


def test_release_domain_lock_deletes_when_value_matches():
    redis = MagicMock()
    redis.get.return_value = b"worker-1:sess-123:1738253400"

    release_domain_lock(redis, "example.com", "worker-1", "sess-123")

    redis.delete.assert_called_once_with(f"{LOCK_KEY_PREFIX}example.com")


def test_release_domain_lock_no_delete_when_value_mismatch():
    redis = MagicMock()
    redis.get.return_value = b"other-worker:sess-456:1738253400"

    release_domain_lock(redis, "example.com", "worker-1", "sess-123")

    redis.delete.assert_not_called()


def test_release_domain_lock_no_op_when_key_missing():
    redis = MagicMock()
    redis.get.return_value = None

    release_domain_lock(redis, "example.com", "worker-1", "sess-123")

    redis.delete.assert_not_called()


# --- throttle_wait ---


def test_throttle_wait_skips_when_disable_throttle():
    redis = MagicMock()
    config = _lock_config(disable_throttle=True)

    throttle_wait(redis, "example.com", "sess-123", config, "standard")

    redis.get.assert_not_called()
    redis.set.assert_called_once()
    call = redis.set.call_args
    assert call[0][0] == f"{THROTTLE_KEY_PREFIX}example.com"
    assert call[1].get("ex") == 60


def test_throttle_wait_skips_when_mode_debug():
    redis = MagicMock()
    config = _lock_config(disable_throttle=False)

    throttle_wait(redis, "example.com", "sess-123", config, "debug")

    redis.set.assert_called_once()
    assert redis.set.call_args[1].get("ex") == 60


def test_throttle_wait_waits_when_within_min_delay():
    redis = MagicMock()
    now_ms = int(time.time() * 1000)
    last_ms = now_ms - 500
    redis.get.return_value = str(last_ms).encode()
    config = _lock_config(min_delay_ms=2000)

    with patch("worker.locking.time.sleep") as mock_sleep:
        throttle_wait(redis, "example.com", "sess-123", config, "standard")

    mock_sleep.assert_called_once()
    wait_s = mock_sleep.call_args[0][0]
    assert 1.4 <= wait_s <= 1.6
    redis.set.assert_called()


def test_throttle_wait_no_wait_when_elapsed_exceeds_min_delay():
    redis = MagicMock()
    now_ms = int(time.time() * 1000)
    last_ms = now_ms - 5000
    redis.get.return_value = str(last_ms).encode()
    config = _lock_config(min_delay_ms=2000)

    with patch("worker.locking.time.sleep") as mock_sleep:
        throttle_wait(redis, "example.com", "sess-123", config, "standard")

    mock_sleep.assert_not_called()
    redis.set.assert_called_once()


def test_throttle_wait_no_wait_when_key_missing():
    redis = MagicMock()
    redis.get.return_value = None
    config = _lock_config(min_delay_ms=2000)

    with patch("worker.locking.time.sleep") as mock_sleep:
        throttle_wait(redis, "example.com", "sess-123", config, "standard")

    mock_sleep.assert_not_called()
    redis.set.assert_called_once()


# --- update_throttle_after_session ---


def test_update_throttle_after_session_sets_key():
    redis = MagicMock()
    config = _lock_config()

    update_throttle_after_session(redis, "example.com", config)

    redis.set.assert_called_once()
    key, value = redis.set.call_args[0][:2]
    assert key == f"{THROTTLE_KEY_PREFIX}example.com"
    assert value.isdigit()
    assert redis.set.call_args[1].get("ex") == 60


def test_update_throttle_after_session_no_op_when_disable_throttle():
    redis = MagicMock()
    config = _lock_config(disable_throttle=True)

    update_throttle_after_session(redis, "example.com", config)

    redis.set.assert_not_called()


# --- key constants ---


def test_lock_key_prefix():
    assert LOCK_KEY_PREFIX == "lock:domain:"


def test_throttle_key_prefix():
    assert THROTTLE_KEY_PREFIX == "throttle:domain:"
