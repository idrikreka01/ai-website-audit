"""
Service layer for audit business logic.

This module contains the business logic for audit operations, coordinating
between the repository layer and providing a clean interface for the API routes.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID
from urllib.parse import urlparse, urlunparse

from api.queue import enqueue_audit_job
from api.repositories.audit_repository import AuditRepository
from api.schemas import (
    AuditSessionResponse,
    AuditPageResponse,
    ArtifactResponse,
    CreateAuditResponse,
)
from shared.logging import get_logger


logger = get_logger(__name__)

# Current crawl policy version (hardcoded for MVP; can be made configurable later).
CRAWL_POLICY_VERSION = "v1.0"


def normalize_url(url: str) -> str:
    """
    Normalize a URL to a consistent format.

    - Requires scheme (validated by Pydantic HttpUrl before this function)
    - Removes trailing slashes from path (except root "/")
    - Normalizes to lowercase hostname

    Note: The URL is expected to have a scheme already (enforced by HttpUrl
    validation in the request schema). The scheme check here is defensive.
    """
    parsed = urlparse(str(url))

    # Scheme should already be present (validated by HttpUrl), but check defensively
    scheme = parsed.scheme or "https"
    if scheme not in ("http", "https"):
        raise ValueError(f"URL must use http:// or https:// scheme, got: {scheme}")

    # Normalize hostname to lowercase
    netloc = parsed.netloc.lower() if parsed.netloc else None
    if not netloc:
        raise ValueError("URL must include a hostname")

    # Remove trailing slash from path (but keep root path "/")
    path = parsed.path.rstrip("/") or "/"

    normalized = urlunparse(
        (
            scheme,
            netloc,
            path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )

    return normalized


class AuditService:
    """Service for audit operations."""

    def __init__(self, repository: AuditRepository):
        self.repository = repository

    def create_audit_session(
        self,
        *,
        url: str,
        mode: str,
    ) -> CreateAuditResponse:
        """
        Create a new audit session.

        Validates and normalizes the URL, creates the session record with
        status='queued', and returns the session ID and status.

        TODO: Enqueue job in Redis queue (not implemented yet).
        """
        # Normalize URL
        normalized_url = normalize_url(url)

        # Minimal config snapshot for MVP (can be expanded later)
        config_snapshot = {
            "mode": mode,
            "crawl_policy_version": CRAWL_POLICY_VERSION,
        }

        # Create session
        session_data = self.repository.create_session(
            url=normalized_url,
            mode=mode,
            crawl_policy_version=CRAWL_POLICY_VERSION,
            config_snapshot=config_snapshot,
        )

        logger.info(
            "audit_session_created",
            session_id=str(session_data["id"]),
            url=normalized_url,
            mode=mode,
        )

        # Enqueue job in Redis queue
        try:
            enqueue_audit_job(session_data["id"], normalized_url)
        except Exception as e:
            # Log the error but don't fail the request - the session is created
            # and can be retried manually if needed
            logger.error(
                "job_enqueue_failed_after_session_creation",
                error=str(e),
                error_type=type(e).__name__,
                session_id=str(session_data["id"]),
            )
            # Re-raise to let the route handler return an appropriate error
            raise

        return CreateAuditResponse(
            id=session_data["id"],
            status="queued",
            url=normalized_url,
        )

    def get_audit_session(self, session_id: UUID) -> Optional[AuditSessionResponse]:
        """
        Get an audit session by ID, including associated pages.

        Returns None if the session is not found.
        """
        session_data = self.repository.get_session_by_id(session_id)
        if session_data is None:
            return None

        # Fetch associated pages
        pages_data = self.repository.get_pages_by_session_id(session_id)

        # Convert pages to response models
        pages = [
            AuditPageResponse(
                id=page["id"],
                session_id=page["session_id"],
                page_type=page["page_type"],
                viewport=page["viewport"],
                status=page["status"],
                load_timings=page["load_timings"],
                low_confidence_reasons=page["low_confidence_reasons"],
            )
            for page in pages_data
        ]

        return AuditSessionResponse(
            id=session_data["id"],
            url=session_data["url"],
            status=session_data["status"],
            created_at=session_data["created_at"],
            final_url=session_data["final_url"],
            mode=session_data["mode"],
            retention_policy=session_data["retention_policy"],
            attempts=session_data["attempts"],
            error_summary=session_data["error_summary"],
            crawl_policy_version=session_data["crawl_policy_version"],
            config_snapshot=session_data["config_snapshot"],
            low_confidence=session_data["low_confidence"],
            pages=pages,
        )

    def get_audit_artifacts(self, session_id: UUID) -> Optional[list[ArtifactResponse]]:
        """
        Get all artifacts for an audit session.

        Returns None if the session is not found, or an empty list if the
        session exists but has no artifacts.
        """
        # Verify session exists
        session_data = self.repository.get_session_by_id(session_id)
        if session_data is None:
            return None

        # Fetch artifacts
        artifacts_data = self.repository.get_artifacts_by_session_id(session_id)

        artifacts = [
            ArtifactResponse(
                id=artifact["id"],
                session_id=artifact["session_id"],
                page_id=artifact["page_id"],
                type=artifact["type"],
                storage_uri=artifact["storage_uri"],
                size_bytes=artifact["size_bytes"],
                created_at=artifact["created_at"],
                retention_until=artifact["retention_until"],
                checksum=artifact["checksum"],
            )
            for artifact in artifacts_data
        ]

        return artifacts
