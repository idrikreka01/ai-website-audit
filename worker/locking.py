"""
Redis domain lock and throttle helpers for crawl jobs.

Ensures one active crawl per domain and enforces per-domain delay.
All events are logged with session_id and domain. No behavior change to crawl outputs.
"""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from shared.logging import get_logger
from worker.constants import LOCK_KEY_PREFIX, THROTTLE_KEY_PREFIX

if TYPE_CHECKING:
    from redis import Redis

    from shared.config import AppConfig

logger = get_logger(__name__)


class DomainLockTimeoutError(Exception):
    """Raised when domain lock could not be acquired after max retries."""


def normalize_domain(url_or_host: str) -> str:
    """
    Normalize domain: lowercase, strip protocol and optional www.

    Examples:
        https://www.example.com/path -> example.com
        example.com -> example.com
    """
    s = url_or_host.strip().lower()
    if "://" in s:
        parsed = urlparse(s)
        netloc = parsed.netloc or s
    else:
        netloc = s
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or s


def _lock_key(domain: str) -> str:
    return f"{LOCK_KEY_PREFIX}{domain}"


def _throttle_key(domain: str) -> str:
    return f"{THROTTLE_KEY_PREFIX}{domain}"


def _lock_value(worker_id: str, session_id: str) -> str:
    ts = int(time.time())
    return f"{worker_id}:{session_id}:{ts}"


def acquire_domain_lock(
    redis_client: Redis[bytes],
    domain: str,
    worker_id: str,
    session_id: str,
    config: AppConfig,
) -> None:
    """
    Acquire per-domain lock; retry with exponential backoff (max 3 attempts).

    Raises DomainLockTimeoutError if lock cannot be acquired after max retries.
    Logs lock.acquire.success, lock.acquire.retry, lock.acquire.timeout with session_id and domain.
    """
    key = _lock_key(domain)
    ttl = config.domain_lock_ttl_seconds
    max_retries = config.domain_lock_max_retries
    base_ms = config.domain_lock_backoff_base_ms

    for attempt in range(max_retries):
        value = _lock_value(worker_id, session_id)
        acquired = redis_client.set(key, value, nx=True, ex=ttl)
        if acquired:
            logger.info(
                "lock.acquire.success",
                domain=domain,
                session_id=session_id,
                worker_id=worker_id,
                attempt=attempt + 1,
            )
            return

        wait_ms = base_ms * (2**attempt) + random.randint(0, 500)
        logger.info(
            "lock.acquire.retry",
            domain=domain,
            session_id=session_id,
            attempt=attempt + 1,
            max_retries=max_retries,
            wait_ms=wait_ms,
        )
        if attempt < max_retries - 1:
            time.sleep(wait_ms / 1000.0)

    logger.error(
        "lock.acquire.timeout",
        domain=domain,
        session_id=session_id,
        max_retries_exceeded=max_retries,
    )
    raise DomainLockTimeoutError(f"Domain lock timeout for {domain} after {max_retries} attempts")


def release_domain_lock(
    redis_client: Redis[bytes],
    domain: str,
    worker_id: str,
    session_id: str,
) -> None:
    """
    Release per-domain lock if we hold it (value matches worker_id:session_id).

    Logs lock.release.success or lock.release.stale with session_id and domain.
    """
    key = _lock_key(domain)
    raw = redis_client.get(key)
    if raw is None:
        logger.debug(
            "lock.release.missing",
            domain=domain,
            session_id=session_id,
        )
        return

    current = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    prefix = f"{worker_id}:{session_id}:"
    if current.startswith(prefix):
        redis_client.delete(key)
        logger.info(
            "lock.release.success",
            domain=domain,
            session_id=session_id,
        )
    else:
        logger.warning(
            "lock.release.stale",
            domain=domain,
            session_id=session_id,
            lock_value_mismatch=True,
        )


def throttle_wait(
    redis_client: Redis[bytes],
    domain: str,
    session_id: str,
    config: AppConfig,
    mode: str,
) -> None:
    """
    Enforce per-domain minimum delay: wait if needed, then set throttle key.

    Skips wait when disable_throttle or mode=debug. Logs throttle.wait or throttle.skip
    with session_id and domain.
    """
    if config.disable_throttle or mode == "debug":
        logger.info(
            "throttle.skip",
            domain=domain,
            session_id=session_id,
            reason="debug_mode" if mode == "debug" else "testing",
        )
        _set_throttle_timestamp(redis_client, domain, config)
        return

    key = _throttle_key(domain)
    min_delay_ms = config.domain_min_delay_ms
    now_ms = int(time.time() * 1000)
    raw = redis_client.get(key)
    if raw is not None:
        try:
            last_ms = int(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            elapsed_ms = now_ms - last_ms
            if elapsed_ms < min_delay_ms:
                wait_ms = min_delay_ms - elapsed_ms
                logger.info(
                    "throttle.wait",
                    domain=domain,
                    session_id=session_id,
                    wait_ms=wait_ms,
                )
                time.sleep(wait_ms / 1000.0)
        except (ValueError, TypeError):
            pass

    _set_throttle_timestamp(redis_client, domain, config)


def _set_throttle_timestamp(
    redis_client: Redis[bytes],
    domain: str,
    config: AppConfig,
) -> None:
    """Set throttle key to current timestamp (ms) with TTL."""
    key = _throttle_key(domain)
    now_ms = int(time.time() * 1000)
    redis_client.set(key, str(now_ms), ex=config.domain_throttle_ttl_seconds)


def update_throttle_after_session(
    redis_client: Redis[bytes],
    domain: str,
    config: AppConfig,
) -> None:
    """
    Update per-domain last-access timestamp after session completes.

    Call from job finally block so next session respects min delay.
    """
    if config.disable_throttle:
        return
    _set_throttle_timestamp(redis_client, domain, config)
