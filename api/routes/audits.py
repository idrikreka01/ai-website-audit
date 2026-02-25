"""
Route handlers for audit endpoints.

This module defines the FastAPI route handlers for the audit API,
following the contracts specified in TECH_SPEC_V1.md.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api.db import get_db_session
from api.repositories.audit_repository import AuditRepository
from api.schemas import (
    ArtifactResponse,
    AuditQuestionResponse,
    AuditReportResponse,
    AuditResultResponse,
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
        logger.error(
            "audit_question_creation_error",
            error=error_msg,
            error_type=type(e).__name__,
            category=request.category,
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


@router.get(
    "/questions/{question_id}/results",
    response_model=list[AuditResultResponse],
    summary="Get all results for a specific question",
)
def get_question_results(
    question_id: int,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> list[AuditResultResponse]:
    """
    Get all audit results for a specific question.

    Returns all results across all sessions for the given question.
    """
    results = service.get_results_by_question(question_id)
    logger.debug(
        "audit_question_results_retrieved",
        question_id=question_id,
        count=len(results),
    )
    return results


@router.get(
    "/questions/{question_id}",
    response_model=AuditQuestionResponse,
    summary="Get audit question by ID",
)
def get_question(
    question_id: int,
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
    question_id: int,
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
    question_id: int,
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


@router.get(
    "/results/{result_id}",
    response_model=AuditResultResponse,
    summary="Get an audit result by ID",
)
def get_result(
    result_id: int,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> AuditResultResponse:
    """
    Get an audit result by ID.

    Returns 404 if the result is not found.
    """
    result = service.get_result(result_id)
    if result is None:
        logger.warning("audit_result_not_found", result_id=result_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit result {result_id} not found",
        )
    logger.debug("audit_result_retrieved", result_id=result_id)
    return result


@router.get(
    "/{session_id}/results",
    response_model=list[AuditResultResponse],
    summary="Get audit results for a session",
)
def get_audit_results(
    session_id: UUID,
    service: Annotated[AuditService, Depends(get_audit_service)],
) -> list[AuditResultResponse]:
    """
    Get all audit results for a session.

    Returns all results for the given session. Returns an empty list if the
    session exists but has no results. Returns 404 if the session is not found.
    """
    bind_request_context(session_id=str(session_id))

    session = service.get_audit_session(session_id)
    if session is None:
        logger.warning("audit_session_not_found_for_results", session_id=str(session_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit session {session_id} not found",
        )

    results = service.get_results_by_session(session_id)
    logger.debug(
        "audit_results_retrieved",
        session_id=str(session_id),
        result_count=len(results),
    )
    return results


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


@router.get(
    "/{session_id}/report",
    response_model=AuditReportResponse,
    summary="Get JSON report for audit session",
)
def get_audit_report(
    session_id: UUID,
    service: Annotated[AuditService, Depends(get_audit_service)] = ...,
) -> AuditReportResponse:
    """
    Generate and return JSON report for audit session.

    Returns a JSON response with audit results, ordered by severity and filtered by tier logic.
    """
    bind_request_context(session_id=str(session_id))

    session = service.get_audit_session(session_id)
    if session is None:
        logger.warning("audit_session_not_found_for_report", session_id=str(session_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit session {session_id} not found",
        )

    try:
        from worker.report_generator import generate_audit_report
        from worker.repository import AuditRepository

        repository = AuditRepository(service.repository.session)
        report_data = generate_audit_report(session_id, repository)

        if "error" in report_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=report_data.get("error", "Session not found"),
            )

        logger.info(
            "json_report_generated",
            session_id=str(session_id),
            question_count=len(report_data.get("questions", [])),
        )

        return AuditReportResponse(**report_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "json_report_generation_failed",
            session_id=str(session_id),
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate JSON report: {str(e)}",
        )


@router.post(
    "/{session_id}/report/pdf/generate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate PDF report for audit session",
)
def generate_audit_report_pdf(
    session_id: UUID,
    service: Annotated[AuditService, Depends(get_audit_service)] = ...,
) -> dict:
    """
    Trigger PDF report generation for audit session.

    Returns 202 Accepted if generation started, or 404 if session not found.
    """
    bind_request_context(session_id=str(session_id))

    session = service.get_audit_session(session_id)
    if session is None:
        logger.warning("audit_session_not_found_for_pdf_generation", session_id=str(session_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit session {session_id} not found",
        )

    try:
        from urllib.parse import urlparse
        from worker.pdf_generator import generate_and_save_pdf_report
        from worker.repository import AuditRepository

        domain = urlparse(session.url).netloc or "unknown"
        repository = AuditRepository(service.repository.session)
        pdf_uri = generate_and_save_pdf_report(session_id, domain, repository)

        if pdf_uri:
            logger.info(
                "pdf_report_generation_triggered",
                session_id=str(session_id),
                storage_uri=pdf_uri,
            )
            return {
                "status": "generated",
                "session_id": str(session_id),
                "storage_uri": pdf_uri,
                "message": "PDF report generated successfully",
            }
        else:
            logger.warning(
                "pdf_report_generation_failed",
                session_id=str(session_id),
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="PDF report generation failed. Check logs for details.",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "pdf_report_generation_error",
            session_id=str(session_id),
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PDF report: {str(e)}",
        )


@router.get(
    "/{session_id}/report/pdf",
    response_class=FileResponse,
    summary="Get PDF report for audit session",
)
def get_audit_report_pdf(
    session_id: UUID,
    service: Annotated[AuditService, Depends(get_audit_service)] = ...,
) -> FileResponse:
    """
    Get PDF report for audit session.

    Returns the PDF file if it exists, otherwise returns 404.
    """
    bind_request_context(session_id=str(session_id))

    session = service.get_audit_session(session_id)
    if session is None:
        logger.warning("audit_session_not_found_for_pdf", session_id=str(session_id))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit session {session_id} not found",
        )

    artifacts = service.get_audit_artifacts(session_id)
    if artifacts is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    pdf_artifact = next((a for a in artifacts if a.type == "report_pdf"), None)
    if pdf_artifact is None:
        logger.warning(
            "pdf_report_not_found",
            session_id=str(session_id),
            message="PDF report not yet generated",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PDF report not found for session {session_id}. It may still be generating.",
        )

    from pathlib import Path
    from shared.config import get_config

    config = get_config()
    artifacts_root = Path(config.artifacts_dir)
    pdf_path = artifacts_root / pdf_artifact.storage_uri

    if not pdf_path.exists():
        logger.error(
            "pdf_file_not_found_on_disk",
            session_id=str(session_id),
            storage_uri=pdf_artifact.storage_uri,
            expected_path=str(pdf_path),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PDF file not found on disk for session {session_id}",
        )

    logger.info(
        "pdf_report_downloaded",
        session_id=str(session_id),
        storage_uri=pdf_artifact.storage_uri,
        size_bytes=pdf_artifact.size_bytes,
    )

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"audit_report_{session_id}.pdf",
    )
