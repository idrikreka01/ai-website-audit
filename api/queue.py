"""
RQ (Redis Queue) setup for the API service.

This module provides RQ queue configuration and job enqueueing utilities.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

import redis
from rq import Queue

from shared.config import get_config
from shared.logging import get_logger


logger = get_logger(__name__)

# Global Redis connection and queue (initialized on first use).
_redis_conn: Optional[redis.Redis] = None
_queue: Optional[Queue] = None


def get_redis_connection() -> redis.Redis:
    """Get or create the Redis connection."""
    global _redis_conn
    if _redis_conn is None:
        config = get_config()
        if not config.redis_url:
            raise ValueError(
                "REDIS_URL environment variable is required. "
                "Set it to a Redis connection string (e.g., redis://localhost:6379/0)."
            )
        _redis_conn = redis.from_url(config.redis_url)
    return _redis_conn


def get_queue() -> Queue:
    """Get or create the RQ queue."""
    global _queue
    if _queue is None:
        _queue = Queue("audit_jobs", connection=get_redis_connection())
    return _queue


def enqueue_audit_job(session_id: UUID, url: str) -> None:
    """
    Enqueue an audit job in RQ.

    Args:
        session_id: The audit session ID
        url: The normalized URL to audit

    Raises:
        ValueError: If Redis connection fails
        Exception: If job enqueue fails

    Note:
        Uses string-based job path to avoid importing worker code in the API.
        The worker must be importable at runtime when RQ processes the job.
    """
    try:
        queue = get_queue()
        # Use string-based job path to decouple API from worker imports
        job = queue.enqueue(
            "worker.jobs.process_audit_job",
            session_id=str(session_id),
            url=url,
            job_timeout="10m",  # Reasonable timeout for MVP
        )

        logger.info(
            "audit_job_enqueued",
            session_id=str(session_id),
            job_id=job.id,
            url=url,
        )
    except redis.ConnectionError as e:
        logger.error(
            "redis_connection_failed",
            error=str(e),
            session_id=str(session_id),
        )
        raise ValueError(f"Failed to connect to Redis: {str(e)}") from e
    except Exception as e:
        logger.error(
            "job_enqueue_failed",
            error=str(e),
            error_type=type(e).__name__,
            session_id=str(session_id),
        )
        raise
