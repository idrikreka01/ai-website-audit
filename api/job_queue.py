"""
Queue helpers for enqueueing audit jobs.
"""

from __future__ import annotations

from uuid import UUID

import redis
from rq import Queue

from shared.config import get_config
from shared.logging import get_logger

logger = get_logger(__name__)


def enqueue_audit_job(session_id: UUID, url: str) -> str:
    """
    Enqueue an audit job for the worker to process.

    Returns the RQ job ID.
    """
    config = get_config()
    if not config.redis_url:
        raise ValueError("REDIS_URL is not configured")

    redis_conn = redis.from_url(config.redis_url)
    queue = Queue("audit_jobs", connection=redis_conn)

    job = queue.enqueue(
        "worker.jobs.process_audit_job",
        str(session_id),
        url,
        job_timeout=config.audit_job_timeout_seconds,
    )
    logger.info("audit_job_enqueued", session_id=str(session_id), job_id=job.id, url=url)
    return job.id
