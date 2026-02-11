"""
Service layer for audit business logic.

This module contains the business logic for audit operations, coordinating
between the repository layer and providing a clean interface for the API routes.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse, urlunparse
from uuid import UUID

from api.job_queue import enqueue_audit_job
from api.repositories.audit_repository import AuditRepository
from api.schemas import (
    ArtifactResponse,
    AuditPageResponse,
    AuditQuestionResponse,
    AuditSessionResponse,
    CreateAuditQuestionRequest,
    CreateAuditResponse,
    UpdateAuditQuestionRequest,
)
from shared.logging import get_logger

logger = get_logger(__name__)

# Current crawl policy version (hardcoded for MVP; can be made configurable later).
# v1.22: Popup logging records only dismiss events (success/failure).
CRAWL_POLICY_VERSION = "v1.24"


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
        session_id = session_data["id"]

        self.repository.create_log(
            session_id=session_id,
            level="info",
            event_type="artifact",
            message="API: session created",
            details={"api_event": "session_created", "url": normalized_url, "mode": mode},
        )
        logger.info(
            "audit_session_created",
            session_id=str(session_id),
            url=normalized_url,
            mode=mode,
        )

        # Enqueue job in Redis queue
        try:
            enqueue_audit_job(session_id, normalized_url)
        except Exception as e:
            self.repository.create_log(
                session_id=session_id,
                level="error",
                event_type="error",
                message="API: job enqueue failed after session creation",
                details={
                    "api_event": "enqueue_failed",
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            logger.error(
                "job_enqueue_failed_after_session_creation",
                error=str(e),
                error_type=type(e).__name__,
                session_id=str(session_id),
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

        self.repository.create_log(
            session_id=session_id,
            level="info",
            event_type="artifact",
            message="API: session retrieved",
            details={"api_event": "session_retrieved"},
        )

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

        self.repository.create_log(
            session_id=session_id,
            level="info",
            event_type="artifact",
            message="API: artifacts listed",
            details={"api_event": "artifacts_retrieved", "artifact_count": len(artifacts_data)},
        )

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

    def create_question(
        self,
        request: CreateAuditQuestionRequest,
    ) -> AuditQuestionResponse:
        """
        Create a new audit question.

        Returns the created question.
        """
        question_data = self.repository.create_question(
            key=request.key,
            stage=request.stage,
            category=request.category,
            page_type=request.page_type,
            narrative_tier=request.narrative_tier,
            baseline_severity=request.baseline_severity,
            question_text=request.question_text,
            allowed_evidence_types=request.allowed_evidence_types,
            ruleset_version=request.ruleset_version,
            fix_intent=request.fix_intent,
            specific_example_fix_text=request.specific_example_fix_text,
            pass_criteria=request.pass_criteria,
            fail_criteria=request.fail_criteria,
            notes=request.notes,
        )

        logger.info(
            "audit_question_created",
            question_id=str(question_data["id"]),
            key=question_data["key"],
        )

        return AuditQuestionResponse(**question_data)

    def get_question(self, question_id: UUID) -> Optional[AuditQuestionResponse]:
        """
        Get an audit question by ID.

        Returns None if not found.
        """
        question_data = self.repository.get_question_by_id(question_id)
        if question_data is None:
            return None
        return AuditQuestionResponse(**question_data)

    def list_questions(
        self,
        *,
        stage: Optional[str] = None,
        page_type: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[AuditQuestionResponse]:
        """
        List audit questions with optional filters.

        Returns a list of questions.
        """
        questions_data = self.repository.list_questions(
            stage=stage,
            page_type=page_type,
            category=category,
        )
        return [AuditQuestionResponse(**q) for q in questions_data]

    def update_question(
        self,
        question_id: UUID,
        request: UpdateAuditQuestionRequest,
    ) -> Optional[AuditQuestionResponse]:
        """
        Update an audit question.

        Returns the updated question, or None if not found.
        """
        question_data = self.repository.update_question(
            question_id,
            stage=request.stage,
            category=request.category,
            page_type=request.page_type,
            narrative_tier=request.narrative_tier,
            baseline_severity=request.baseline_severity,
            question_text=request.question_text,
            allowed_evidence_types=request.allowed_evidence_types,
            ruleset_version=request.ruleset_version,
            fix_intent=request.fix_intent,
            specific_example_fix_text=request.specific_example_fix_text,
            pass_criteria=request.pass_criteria,
            fail_criteria=request.fail_criteria,
            notes=request.notes,
        )

        if question_data is None:
            return None

        logger.info("audit_question_updated", question_id=str(question_id))

        return AuditQuestionResponse(**question_data)

    def delete_question(self, question_id: UUID) -> bool:
        """
        Delete an audit question by ID.

        Returns True if deleted, False if not found.
        """
        deleted = self.repository.delete_question(question_id)
        if deleted:
            logger.info("audit_question_deleted", question_id=str(question_id))
        return deleted

    # TODO: Implement new audit_results methods using AuditResultResponse schema
    # def get_results_by_session(self, session_id: str) -> list[AuditResultResponse]:
    #     ...
    #
    # def get_results_by_question(self, question_id: int) -> list[AuditResultResponse]:
    #     ...
    #
    # def get_result(self, result_id: int) -> Optional[AuditResultResponse]:
    #     ...
