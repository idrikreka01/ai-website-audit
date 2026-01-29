"""
Route handlers for audit endpoints.

This module defines the FastAPI route handlers for the audit API,
following the contracts specified in TECH_SPEC_V1.md.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.db import get_db_session
from api.repositories.audit_repository import AuditRepository
from api.schemas import (
    ArtifactResponse,
    AuditSessionResponse,
    CreateAuditRequest,
    CreateAuditResponse,
)
from api.services.audit_service import AuditService
from shared.logging import bind_request_context, get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/audits", tags=["audits"])


def get_audit_service(session: Annotated[Session, Depends(get_db_session)]) -> AuditService:
    """Dependency to get an AuditService instance."""
    repository = AuditRepository(session)
    return AuditService(repository)


@router.post(
    "",
    response_model=CreateAuditResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new audit session",
)
def create_audit(
    request: CreateAuditRequest,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> CreateAuditResponse:
    """
    Create a new audit session.

    Validates and normalizes the URL, creates a session record with status='queued',
    and returns the session ID. The actual crawl will be enqueued separately
    (Redis integration pending).
    """
    try:
        response = service.create_audit_session(
            url=str(request.url),
            mode=request.mode,
        )

        bind_request_context(session_id=str(response.id))
        logger.info(
            "audit_creation_requested",
            url=str(request.url),
            mode=request.mode,
        )

        return response
    except ValueError as e:
        logger.warning("audit_creation_failed", error=str(e), url=str(request.url))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid URL: {str(e)}",
        )
    except Exception as e:
        # Check if it's a Redis/enqueue error
        error_msg = str(e)
        if "Redis" in error_msg or "redis" in error_msg or "enqueue" in error_msg.lower():
            logger.error(
                "job_enqueue_error",
                error=error_msg,
                error_type=type(e).__name__,
                url=str(request.url),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to enqueue audit job. Please try again later.",
            )
        logger.error(
            "audit_creation_error",
            error=error_msg,
            error_type=type(e).__name__,
            url=str(request.url),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create audit session",
        )


@router.get(
    "/{session_id}",
    response_model=AuditSessionResponse,
    summary="Get audit session by ID",
)
def get_audit(
    session_id: UUID,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> AuditSessionResponse:
    """
    Get audit session metadata by ID.

    Returns the session metadata including status, timestamps, and associated
    pages (if any). Returns 404 if the session is not found.
    """
    bind_request_context(session_id=str(session_id))

    session = service.get_audit_session(session_id)
    if session is None:
        logger.warning("audit_session_not_found", session_id=str(session_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit session {session_id} not found",
        )

    logger.debug("audit_session_retrieved", session_id=str(session_id))
    return session


@router.get(
    "/{session_id}/artifacts",
    response_model=list[ArtifactResponse],
    summary="Get artifacts for an audit session",
)
def get_audit_artifacts(
    session_id: UUID,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> list[ArtifactResponse]:
    """
    Get all artifacts for an audit session.

    Returns a list of artifact metadata (screenshots, text, features JSON, etc.)
    for the given session. Returns an empty list if the session exists but has
    no artifacts. Returns 404 if the session is not found.
    """
    bind_request_context(session_id=str(session_id))

    artifacts = service.get_audit_artifacts(session_id)
    if artifacts is None:
        logger.warning("audit_session_not_found_for_artifacts", session_id=str(session_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit session {session_id} not found",
        )

    logger.debug(
        "audit_artifacts_retrieved",
        session_id=str(session_id),
        artifact_count=len(artifacts),
    )
    return artifacts
