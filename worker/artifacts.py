"""
Artifact persistence: screenshot, visible_text, features_json, html_gz.

Encapsulates storage writes, repository.create_artifact, and artifact logs.
Unifies HTML retention decision via should_store_html.
No behavior change.
"""

from __future__ import annotations

from uuid import UUID

from worker.repository import AuditRepository
from worker.storage import (
    build_artifact_path,
    get_storage_uri,
    write_html_gz,
    write_json,
    write_screenshot,
    write_text,
)


def should_store_html(
    first_time: bool,
    mode: str,
    low_confidence: bool,
    error_summary: str | None,
) -> bool:
    """
    Return True when html.gz should be stored.

    Store when: first_time OR mode in ("debug", "evidence_pack") OR low_confidence OR error.
    """
    return (
        first_time
        or mode in ("debug", "evidence_pack")
        or low_confidence
        or error_summary is not None
    )


def save_screenshot(
    repository: AuditRepository,
    session_id: UUID,
    page_id: UUID,
    page_type: str,
    viewport: str,
    screenshot_bytes: bytes | None,
) -> str | None:
    """
    Write screenshot to storage, create artifact and log. Returns "screenshot" if saved, else None.
    """
    if not screenshot_bytes:
        return None
    path = build_artifact_path(session_id, page_type, viewport, "screenshot")
    size, checksum = write_screenshot(path, screenshot_bytes)
    storage_uri = get_storage_uri(path)
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
        details={"size_bytes": size, "storage_uri": storage_uri},
    )
    return "screenshot"


def save_visible_text(
    repository: AuditRepository,
    session_id: UUID,
    page_id: UUID,
    page_type: str,
    viewport: str,
    visible_text: str,
) -> str:
    """Write visible text to storage, create artifact and log. Returns "visible_text"."""
    path = build_artifact_path(session_id, page_type, viewport, "visible_text")
    size, checksum = write_text(path, visible_text)
    storage_uri = get_storage_uri(path)
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
        details={"size_bytes": size, "storage_uri": storage_uri},
    )
    return "visible_text"


def save_features_json(
    repository: AuditRepository,
    session_id: UUID,
    page_id: UUID,
    page_type: str,
    viewport: str,
    features: dict,
) -> str:
    """Write features JSON to storage, create artifact and log. Returns "features_json"."""
    path = build_artifact_path(session_id, page_type, viewport, "features_json")
    size, checksum = write_json(path, features)
    storage_uri = get_storage_uri(path)
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
        details={"size_bytes": size, "storage_uri": storage_uri},
    )
    return "features_json"


def save_html_gz(
    repository: AuditRepository,
    session_id: UUID,
    page_id: UUID,
    page_type: str,
    viewport: str,
    html_content: str,
) -> str:
    """Write HTML (gzip) to storage, create artifact and log. Returns "html_gz"."""
    path = build_artifact_path(session_id, page_type, viewport, "html_gz")
    size, checksum = write_html_gz(path, html_content)
    storage_uri = get_storage_uri(path)
    repository.create_artifact(
        session_id=session_id,
        page_id=page_id,
        artifact_type="html_gz",
        storage_uri=storage_uri,
        size_bytes=size,
        checksum=checksum,
    )
    repository.create_log(
        session_id=session_id,
        level="info",
        event_type="artifact",
        message="HTML (gzip) saved",
        details={"size_bytes": size, "storage_uri": storage_uri},
    )
    return "html_gz"
