"""
RQ job handlers for audit processing.

Thin entrypoint: open DB session, create repository, call orchestrator, handle exceptions.
Lock and throttle at job start, released in finally (TECH_SPEC_V1.1.md).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse
from uuid import UUID

from rq import get_current_connection

from shared.config import get_config
from shared.logging import bind_request_context, get_logger
from worker.db import get_db_session
from worker.error_summary import get_user_safe_error_summary
from worker.locking import (
    DomainLockTimeoutError,
    acquire_domain_lock,
    normalize_domain,
    release_domain_lock,
    throttle_wait,
    update_throttle_after_session,
)
from worker.orchestrator import run_audit_session
from worker.repository import AuditRepository

logger = get_logger(__name__)


def process_audit_job(session_id: str, url: str) -> None:
    """
    RQ job handler to process an audit session with homepage crawling.

    Acquires domain lock before crawl and releases on completion (success, failure, or partial).
    Enforces per-domain throttle delay via throttle:domain:{domain}.
    Lock conflicts retry with backoff (max 3); all lock/throttle events are structured logs.

    Args:
        session_id: The audit session UUID as a string
        url: The normalized URL to audit
    """
    session_uuid = UUID(session_id)
    domain = normalize_domain(urlparse(url).netloc or url)
    bind_request_context(session_id=session_id, domain=domain)

    logger.info("audit_job_started", url=url)

    config = get_config()
    redis_client = None

    with get_db_session() as db_session:
        repository = AuditRepository(db_session)

        session_data = repository.get_session_by_id(session_uuid)
        if session_data is None:
            logger.error("audit_session_not_found", session_id=session_id)
            raise ValueError(f"Audit session {session_id} not found")

        mode = session_data["mode"]

        if not config.disable_locks:
            redis_client = get_current_connection()
            throttle_wait(redis_client, domain, session_id, config, mode)
            worker_id = f"worker-{os.getpid()}"
            try:
                acquire_domain_lock(redis_client, domain, worker_id, session_id, config)
            except DomainLockTimeoutError as e:
                logger.error(
                    "lock.acquire.timeout",
                    domain=domain,
                    session_id=session_id,
                    error=str(e),
                )
                repository.update_session_status(
                    session_uuid, "failed", error_summary="Domain lock timeout"
                )
                repository.create_log(
                    session_id=session_uuid,
                    level="error",
                    event_type="timeout",
                    message="Domain lock timeout",
                    details={"domain": domain, "error": str(e)},
                )
                raise

        try:
            run_audit_session(url, session_uuid, repository)
        except Exception as e:
            logger.error("audit_job_error", error=str(e), error_type=type(e).__name__)
            repository.update_session_status(
                session_uuid,
                "failed",
                error_summary=get_user_safe_error_summary(e, fallback="Audit failed"),
            )
            repository.create_log(
                session_id=session_uuid,
                level="error",
                event_type="error",
                message="Audit job failed",
                details={"error": str(e), "error_type": type(e).__name__},
            )
            raise
        finally:
            if not config.disable_locks and redis_client is not None:
                worker_id = f"worker-{os.getpid()}"
                release_domain_lock(redis_client, domain, worker_id, session_id)
                update_throttle_after_session(redis_client, domain, config)

    logger.info("audit_job_completed", session_id=session_id)
