"""
Service layer for audit business logic.

This module contains the business logic for audit operations, coordinating
between the repository layer and providing a clean interface for the API routes.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse, urlunparse
from uuid import UUID

from sqlalchemy import select

from api.job_queue import enqueue_audit_job
from api.repositories.audit_repository import AuditRepository
from api.schemas import (
    ArtifactResponse,
    AuditPageResponse,
    AuditQuestionResponse,
    AuditResultResponse,
    AuditSessionResponse,
    CreateAuditQuestionRequest,
    CreateAuditResponse,
    UpdateAuditQuestionRequest,
)
from shared.db import get_audit_questions_table
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
            homepage_ok=session_data.get("homepage_ok", False),
            pdp_ok=session_data.get("pdp_ok", False),
            cart_ok=session_data.get("cart_ok", False),
            checkout_ok=session_data.get("checkout_ok", False),
            page_coverage_score=session_data.get("page_coverage_score", 0),
            ai_audit_score=session_data.get("ai_audit_score"),
            ai_audit_flag=session_data.get("ai_audit_flag"),
            functional_flow_score=session_data.get("functional_flow_score", 0),
            functional_flow_details=session_data.get("functional_flow_details"),
            overall_score_percentage=session_data.get("overall_score_percentage"),
            needs_manual_review=session_data.get("needs_manual_review", False),
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
        questions_table = get_audit_questions_table()

        insert_stmt = (
            questions_table.insert()
            .values(
                category=request.category,
                question=request.question,
                ai_criteria=request.ai_criteria,
                tier=request.tier,
                severity=request.severity,
                bar_chart_category=request.bar_chart_category,
                exact_fix=request.exact_fix,
                page_type=request.page_type,
            )
            .returning(questions_table.c.question_id)
        )

        result = self.repository.session.execute(insert_stmt)
        question_id = result.scalar_one()
        self.repository.session.flush()

        select_stmt = select(questions_table).where(questions_table.c.question_id == question_id)
        row = self.repository.session.execute(select_stmt).one()
        question_data = dict(row._mapping)

        logger.info(
            "audit_question_created",
            question_id=question_id,
            category=request.category,
        )

        return AuditQuestionResponse(**question_data)

    def get_question(self, question_id: int) -> Optional[AuditQuestionResponse]:
        """
        Get an audit question by ID.

        Returns None if not found.
        """
        questions_table = get_audit_questions_table()
        stmt = select(questions_table).where(questions_table.c.question_id == question_id)
        result = self.repository.session.execute(stmt).first()
        if result is None:
            return None
        question_data = dict(result._mapping)
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
        Note: stage parameter maps to category (Awareness/Consideration/Conversion).
        """
        questions_table = get_audit_questions_table()
        stmt = select(questions_table)

        conditions = []
        category_filter = stage if stage is not None else category
        if category_filter is not None:
            conditions.append(questions_table.c.category == category_filter)
        if page_type is not None:
            conditions.append(questions_table.c.page_type == page_type)

        if conditions:
            from sqlalchemy import and_

            stmt = stmt.where(and_(*conditions))

        stmt = stmt.order_by(questions_table.c.question_id)
        results = self.repository.session.execute(stmt).all()
        questions_data = [dict(row._mapping) for row in results]
        return [AuditQuestionResponse(**q) for q in questions_data]

    def update_question(
        self,
        question_id: int,
        request: UpdateAuditQuestionRequest,
    ) -> Optional[AuditQuestionResponse]:
        """
        Update an audit question.

        Returns the updated question, or None if not found.
        """
        questions_table = get_audit_questions_table()

        update_values = {}
        if request.category is not None:
            update_values["category"] = request.category
        if request.question is not None:
            update_values["question"] = request.question
        if request.ai_criteria is not None:
            update_values["ai_criteria"] = request.ai_criteria
        if request.tier is not None:
            update_values["tier"] = request.tier
        if request.severity is not None:
            update_values["severity"] = request.severity
        if request.bar_chart_category is not None:
            update_values["bar_chart_category"] = request.bar_chart_category
        if request.exact_fix is not None:
            update_values["exact_fix"] = request.exact_fix
        if request.page_type is not None:
            update_values["page_type"] = request.page_type

        if not update_values:
            return self.get_question(question_id)

        update_stmt = (
            questions_table.update()
            .where(questions_table.c.question_id == question_id)
            .values(**update_values)
        )
        self.repository.session.execute(update_stmt)
        self.repository.session.flush()

        logger.info("audit_question_updated", question_id=question_id)

        return self.get_question(question_id)

    def delete_question(self, question_id: int) -> bool:
        """
        Delete an audit question by ID.

        Returns True if deleted, False if not found.
        """
        questions_table = get_audit_questions_table()

        check_stmt = select(questions_table).where(questions_table.c.question_id == question_id)
        exists = self.repository.session.execute(check_stmt).first() is not None

        if not exists:
            return False

        delete_stmt = questions_table.delete().where(questions_table.c.question_id == question_id)
        self.repository.session.execute(delete_stmt)
        self.repository.session.flush()

        logger.info("audit_question_deleted", question_id=question_id)
        return True

    def get_results_by_session(self, session_id: UUID) -> list[AuditResultResponse]:
        """
        Get all audit results for a session.

        Returns a list of results.
        """
        from urllib.parse import urlparse

        session_data = self.repository.get_session_by_id(session_id)
        if not session_data:
            return []

        domain = urlparse(session_data.get("url", "")).netloc.replace("www.", "")
        session_id_str = f"{domain}__{session_id}"

        results_data = self.repository.get_audit_results_by_session_id(session_id_str)
        return [AuditResultResponse(**r) for r in results_data]

    def get_results_by_question(self, question_id: int) -> list[AuditResultResponse]:
        """
        Get all audit results for a specific question.

        Returns a list of results.
        """
        results_data = self.repository.get_audit_results_by_question_id(question_id)
        return [AuditResultResponse(**r) for r in results_data]

    def get_result(self, result_id: int) -> Optional[AuditResultResponse]:
        """
        Get a single audit result by ID.

        Returns the result, or None if not found.
        """
        result_data = self.repository.get_audit_result_by_id(result_id)
        if result_data is None:
            return None
        return AuditResultResponse(**result_data)
