"""
RQ job handlers for audit processing.

Thin entrypoint: open DB session, create repository, call orchestrator, handle top-level exceptions.
"""

from __future__ import annotations

from urllib.parse import urlparse
from uuid import UUID

from shared.logging import bind_request_context, get_logger
from worker.db import get_db_session
from worker.orchestrator import run_audit_session
from worker.repository import AuditRepository

logger = get_logger(__name__)


def process_audit_job(session_id: str, url: str) -> None:
    """
    RQ job handler to process an audit session with homepage crawling.

    Args:
        session_id: The audit session UUID as a string
        url: The normalized URL to audit
    """
    session_uuid = UUID(session_id)
    domain = urlparse(url).netloc
    bind_request_context(session_id=session_id, domain=domain)

    logger.info("audit_job_started", url=url)

    with get_db_session() as db_session:
        repository = AuditRepository(db_session)

        session_data = repository.get_session_by_id(session_uuid)
        if session_data is None:
            logger.error("audit_session_not_found", session_id=session_id)
            raise ValueError(f"Audit session {session_id} not found")

        try:
            run_audit_session(url, session_uuid, repository)
        except Exception as e:
            logger.error("audit_job_error", error=str(e), error_type=type(e).__name__)
            repository.update_session_status(session_uuid, "failed", error_summary=str(e))
            repository.create_log(
                session_id=session_uuid,
                level="error",
                event_type="error",
                message=f"Audit job failed: {str(e)}",
                details={"error": str(e), "error_type": type(e).__name__},
            )
            raise

    logger.info("audit_job_completed", session_id=session_id)
