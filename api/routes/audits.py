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
    AuditQuestionResponse,
    AuditSessionResponse,
    CreateAuditQuestionRequest,
    CreateAuditRequest,
    CreateAuditResponse,
    UpdateAuditQuestionRequest,
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


@router.post(
    "/questions",
    response_model=AuditQuestionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new audit question",
)
def create_question(
    request: CreateAuditQuestionRequest,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> AuditQuestionResponse:
    """
    Create a new audit question.

    Creates a new question in the audit question library.
    """
    try:
        response = service.create_question(request)
        logger.info("audit_question_creation_requested")
        return response
    except Exception as e:
        error_msg = str(e)
        if "unique" in error_msg.lower() or "duplicate" in error_msg.lower():
            logger.warning(
                "audit_question_creation_failed_duplicate", key=request.key, error=error_msg
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Question with key '{request.key}' already exists",
            )
        logger.error(
            "audit_question_creation_error",
            error=error_msg,
            error_type=type(e).__name__,
            key=request.key,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create audit question",
        )


@router.get(
    "/questions",
    response_model=list[AuditQuestionResponse],
    summary="List audit questions",
)
def list_questions(
    stage: str | None = None,
    page_type: str | None = None,
    category: str | None = None,
    service: Annotated[AuditService, Depends(get_audit_service)] = ...,
) -> list[AuditQuestionResponse]:
    """
    List audit questions with optional filters.

    Returns all questions matching the optional filters (stage, page_type, category).
    """
    questions = service.list_questions(
        stage=stage,
        page_type=page_type,
        category=category,
    )
    logger.debug(
        "audit_questions_listed",
        count=len(questions),
        filters={"stage": stage, "page_type": page_type, "category": category},
    )
    return questions


# TODO: Implement new audit_results endpoints using AuditResultResponse schema
# @router.get(
#     "/questions/{question_id}/results",
#     response_model=list[AuditResultResponse],
#     summary="Get all results for a specific question",
# )
# def get_question_results(...):
#     ...


@router.get(
    "/questions/{question_id}",
    response_model=AuditQuestionResponse,
    summary="Get audit question by ID",
)
def get_question(
    question_id: UUID,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> AuditQuestionResponse:
    """
    Get an audit question by ID.

    Returns 404 if the question is not found.
    """
    question = service.get_question(question_id)
    if question is None:
        logger.warning("audit_question_not_found", question_id=str(question_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit question {question_id} not found",
        )
    logger.debug("audit_question_retrieved", question_id=str(question_id))
    return question


@router.put(
    "/questions/{question_id}",
    response_model=AuditQuestionResponse,
    summary="Update an audit question",
)
def update_question(
    question_id: UUID,
    request: UpdateAuditQuestionRequest,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> AuditQuestionResponse:
    """
    Update an audit question.

    Updates only the provided fields. Returns 404 if the question is not found.
    """
    question = service.update_question(question_id, request)
    if question is None:
        logger.warning("audit_question_not_found_for_update", question_id=str(question_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit question {question_id} not found",
        )
    logger.debug("audit_question_updated", question_id=str(question_id))
    return question


@router.delete(
    "/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an audit question",
)
def delete_question(
    question_id: UUID,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> None:
    """
    Delete an audit question by ID.

    Returns 404 if the question is not found, 204 if successfully deleted.
    """
    deleted = service.delete_question(question_id)
    if not deleted:
        logger.warning("audit_question_not_found_for_delete", question_id=str(question_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit question {question_id} not found",
        )
    logger.info("audit_question_deleted", question_id=str(question_id))


# TODO: Implement new audit_results endpoints using AuditResultResponse schema
# @router.get(
#     "/results/{result_id}",
#     response_model=AuditResultResponse,
#     summary="Get an audit result by ID",
# )
# def get_result(...):
#     ...


# TODO: Implement new audit_results endpoints using AuditResultResponse schema
# @router.get(
#     "/{session_id}/results",
#     response_model=list[AuditResultResponse],
#     summary="Get audit results for a session",
# )
# def get_audit_results(...):
#     ...


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
        # Do not write to crawl_logs: session_id is not in audit_sessions (FK would fail).
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
        # Do not write to crawl_logs: session_id is not in audit_sessions (FK would fail).
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
