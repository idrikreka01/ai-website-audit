"""
Artifact persistence: screenshot, visible_text, features_json, html_gz.

Encapsulates storage writes, repository.create_artifact, and artifact logs.
DB artifact records created only after successful writes; write failures logged
with context (session_id, page_type, viewport, artifact_type, error_type).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from shared.config import get_config
from shared.logging import get_logger
from worker.repository import AuditRepository
from worker.storage import (
    build_artifact_path,
    build_session_log_artifact_path,
    get_storage_uri,
    write_html_gz,
    write_json,
    write_jsonl,
    write_screenshot,
    write_text,
)

logger = get_logger(__name__)


def should_store_html(
    first_time: bool,
    mode: str,
    low_confidence: bool,
    error_summary: str | None,
) -> bool:
    """
    Return True when html.gz should be stored.

    Store always (policy v1.12).
    """
    return True


def save_screenshot(
    repository: AuditRepository,
    session_id: UUID,
    page_id: UUID,
    page_type: str,
    viewport: str,
    domain: str,
    screenshot_bytes: bytes | None,
) -> Optional[str]:
    """
    Write screenshot to storage; create artifact and log only on success.
    Returns "screenshot" if saved, else None. Write failures are logged with context.
    """
    if not screenshot_bytes:
        return None
    try:
        path = build_artifact_path(session_id, page_type, viewport, "screenshot", domain)
        size, checksum = write_screenshot(path, screenshot_bytes)
        storage_uri = get_storage_uri(path)
    except Exception as e:
        logger.error(
            "artifact_write_failed",
            artifact_type="screenshot",
            session_id=str(session_id),
            page_type=page_type,
            viewport=viewport,
            error=str(e),
            error_type=type(e).__name__,
        )
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="artifact",
            message="Screenshot write failed",
            details={
                "artifact_type": "screenshot",
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise
    repository.create_artifact(
        session_id=session_id,
        page_id=page_id,
        artifact_type="screenshot",
        storage_uri=storage_uri,
        size_bytes=size,
        checksum=checksum,
    )
    repository.create_log(
        session_id=session_id,
        level="info",
        event_type="artifact",
        message="Screenshot saved",
        details={"size_bytes": size, "checksum": checksum, "storage_uri": storage_uri},
    )
    logger.info(
        "artifact_saved",
        artifact_type="screenshot",
        size_bytes=size,
        checksum=checksum,
        storage_uri=storage_uri,
    )
    return "screenshot"


def save_visible_text(
    repository: AuditRepository,
    session_id: UUID,
    page_id: UUID,
    page_type: str,
    viewport: str,
    domain: str,
    visible_text: str,
) -> Optional[str]:
    """Write visible text to storage; create artifact only on success."""
    try:
        path = build_artifact_path(session_id, page_type, viewport, "visible_text", domain)
        size, checksum = write_text(path, visible_text)
        storage_uri = get_storage_uri(path)
    except Exception as e:
        logger.error(
            "artifact_write_failed",
            artifact_type="visible_text",
            session_id=str(session_id),
            page_type=page_type,
            viewport=viewport,
            error=str(e),
            error_type=type(e).__name__,
        )
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="artifact",
            message="Visible text write failed",
            details={
                "artifact_type": "visible_text",
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise
    repository.create_artifact(
        session_id=session_id,
        page_id=page_id,
        artifact_type="visible_text",
        storage_uri=storage_uri,
        size_bytes=size,
        checksum=checksum,
    )
    repository.create_log(
        session_id=session_id,
        level="info",
        event_type="artifact",
        message="Visible text saved",
        details={"size_bytes": size, "checksum": checksum, "storage_uri": storage_uri},
    )
    logger.info(
        "artifact_saved",
        artifact_type="visible_text",
        size_bytes=size,
        checksum=checksum,
        storage_uri=storage_uri,
    )
    return "visible_text"


def save_features_json(
    repository: AuditRepository,
    session_id: UUID,
    page_id: UUID,
    page_type: str,
    viewport: str,
    domain: str,
    features: dict,
) -> Optional[str]:
    """Write features JSON to storage; create artifact only on success."""
    try:
        path = build_artifact_path(session_id, page_type, viewport, "features_json", domain)
        size, checksum = write_json(path, features)
        storage_uri = get_storage_uri(path)
    except Exception as e:
        logger.error(
            "artifact_write_failed",
            artifact_type="features_json",
            session_id=str(session_id),
            page_type=page_type,
            viewport=viewport,
            error=str(e),
            error_type=type(e).__name__,
        )
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="artifact",
            message="Features JSON write failed",
            details={
                "artifact_type": "features_json",
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise
    repository.create_artifact(
        session_id=session_id,
        page_id=page_id,
        artifact_type="features_json",
        storage_uri=storage_uri,
        size_bytes=size,
        checksum=checksum,
    )
    repository.create_log(
        session_id=session_id,
        level="info",
        event_type="artifact",
        message="Features JSON saved",
        details={"size_bytes": size, "checksum": checksum, "storage_uri": storage_uri},
    )
    logger.info(
        "artifact_saved",
        artifact_type="features_json",
        size_bytes=size,
        checksum=checksum,
        storage_uri=storage_uri,
    )
    return "features_json"


def save_html_gz(
    repository: AuditRepository,
    session_id: UUID,
    page_id: UUID,
    page_type: str,
    viewport: str,
    domain: str,
    html_content: str,
) -> Optional[str]:
    """Write HTML (gzip) to storage; create artifact only on success. Returns "html_gz" or None."""
    try:
        path = build_artifact_path(session_id, page_type, viewport, "html_gz", domain)
        size, checksum = write_html_gz(path, html_content)
        storage_uri = get_storage_uri(path)
    except Exception as e:
        logger.error(
            "artifact_write_failed",
            artifact_type="html_gz",
            session_id=str(session_id),
            page_type=page_type,
            viewport=viewport,
            error=str(e),
            error_type=type(e).__name__,
        )
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="artifact",
            message="HTML (gzip) write failed",
            details={
                "artifact_type": "html_gz",
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise
    config = get_config()
    retention_until = datetime.now(timezone.utc) + timedelta(days=config.html_retention_days)
    repository.create_artifact(
        session_id=session_id,
        page_id=page_id,
        artifact_type="html_gz",
        storage_uri=storage_uri,
        size_bytes=size,
        retention_until=retention_until,
        checksum=checksum,
    )
    repository.create_log(
        session_id=session_id,
        level="info",
        event_type="artifact",
        message="HTML (gzip) saved",
        details={
            "size_bytes": size,
            "checksum": checksum,
            "storage_uri": storage_uri,
            "retention_until": retention_until.isoformat(),
        },
    )
    logger.info(
        "artifact_saved",
        artifact_type="html_gz",
        size_bytes=size,
        checksum=checksum,
        storage_uri=storage_uri,
        retention_until=retention_until.isoformat(),
    )
    return "html_gz"


def save_session_logs(
    repository: AuditRepository,
    session_id: UUID,
    domain: str,
) -> bool:
    """
    Export crawl_logs for the session to session_logs.jsonl and create artifact record.

    Session-level artifact (no page_id). Does not alter session status on failure:
    on any exception, logs the error and returns False; caller must not fail the session.
    Returns True if the artifact was written and the DB record created.
    """
    try:
        logs = repository.get_logs_by_session_id(session_id)
        path = build_session_log_artifact_path(domain, session_id)
        size, checksum = write_jsonl(path, logs)
        storage_uri = get_storage_uri(path)
        repository.create_artifact(
            session_id=session_id,
            page_id=None,
            artifact_type="session_logs_jsonl",
            storage_uri=storage_uri,
            size_bytes=size,
            checksum=checksum,
        )
        logger.info(
            "session_log_artifact_saved",
            session_id=str(session_id),
            storage_uri=storage_uri,
            size_bytes=size,
            log_count=len(logs),
        )
        return True
    except Exception as e:
        logger.error(
            "session_log_export_failed",
            session_id=str(session_id),
            error=str(e),
            error_type=type(e).__name__,
        )
        repository.create_log(
            session_id=session_id,
            level="error",
            event_type="artifact",
            message="Session log export failed",
            details={
                "artifact_type": "session_logs_jsonl",
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        return False
