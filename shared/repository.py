"""
Shared repository for audit session, page, artifact, and log data access.

This module provides low-level database access using SQLAlchemy Table objects,
keeping the service layer clean and testable. It can be used by both the API
and worker services.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from shared.db import (
    get_artifacts_table,
    get_audit_pages_table,
    get_audit_question_results_table,
    get_audit_questions_table,
    get_audit_sessions_table,
    get_crawl_logs_table,
)


class AuditRepository:
    """Repository for audit-related database operations."""

    def __init__(self, session: Session):
        self.session = session
        self.sessions_table = get_audit_sessions_table()
        self.pages_table = get_audit_pages_table()
        self.artifacts_table = get_artifacts_table()
        self.logs_table = get_crawl_logs_table()
        self.questions_table = get_audit_questions_table()
        self.question_results_table = get_audit_question_results_table()

    def create_session(
        self,
        *,
        url: str,
        mode: str,
        crawl_policy_version: str,
        config_snapshot: dict,
        retention_policy: str = "standard",
    ) -> dict:
        """
        Create a new audit session with status='queued'.

        Returns the created session as a dict (matching table columns).
        """
        session_id = uuid4()
        now = datetime.now(timezone.utc)

        insert_stmt = self.sessions_table.insert().values(
            id=session_id,
            url=url,
            status="queued",
            created_at=now,
            final_url=None,
            mode=mode,
            retention_policy=retention_policy,
            attempts=0,
            error_summary=None,
            crawl_policy_version=crawl_policy_version,
            config_snapshot=config_snapshot,
            low_confidence=False,
        )

        self.session.execute(insert_stmt)
        self.session.flush()

        # Fetch the created row
        select_stmt = select(self.sessions_table).where(self.sessions_table.c.id == session_id)
        row = self.session.execute(select_stmt).one()
        return dict(row._mapping)

    def get_session_by_id(self, session_id: UUID) -> Optional[dict]:
        """
        Get an audit session by ID.

        Returns the session as a dict, or None if not found.
        """
        stmt = select(self.sessions_table).where(self.sessions_table.c.id == session_id)
        result = self.session.execute(stmt).first()
        if result is None:
            return None
        return dict(result._mapping)

    def get_pages_by_session_id(self, session_id: UUID) -> list[dict]:
        """
        Get all pages for a session.

        Returns a list of page dicts.
        """
        stmt = select(self.pages_table).where(self.pages_table.c.session_id == session_id)
        results = self.session.execute(stmt).all()
        return [dict(row._mapping) for row in results]

    def get_logs_by_session_id(self, session_id: UUID) -> list[dict]:
        """
        Get all crawl_logs for a session in stable order (timestamp, then id).

        Returns a list of log dicts for export to session_logs.jsonl.
        """
        stmt = (
            select(self.logs_table)
            .where(self.logs_table.c.session_id == session_id)
            .order_by(self.logs_table.c.timestamp.asc(), self.logs_table.c.id.asc())
        )
        results = self.session.execute(stmt).all()
        return [dict(row._mapping) for row in results]

    def get_artifacts_by_session_id(self, session_id: UUID) -> list[dict]:
        """
        Get all artifacts for a session.

        Returns a list of artifact dicts.
        """
        stmt = select(self.artifacts_table).where(self.artifacts_table.c.session_id == session_id)
        results = self.session.execute(stmt).all()
        return [dict(row._mapping) for row in results]

    def update_session_status(
        self,
        session_id: UUID,
        status: str,
        *,
        error_summary: Optional[str] = None,
        final_url: Optional[str] = None,
    ) -> None:
        """
        Update an audit session's status.

        Optionally updates error_summary and final_url as well.
        """
        update_values = {"status": status}
        if error_summary is not None:
            update_values["error_summary"] = error_summary
        if final_url is not None:
            update_values["final_url"] = final_url

        update_stmt = (
            self.sessions_table.update()
            .where(self.sessions_table.c.id == session_id)
            .values(**update_values)
        )
        self.session.execute(update_stmt)
        self.session.flush()

    def create_page(
        self,
        *,
        session_id: UUID,
        page_type: str,
        viewport: str,
        status: str = "pending",
        load_timings: Optional[dict] = None,
        low_confidence_reasons: Optional[list[str]] = None,
    ) -> dict:
        """
        Create an audit page record.

        Returns the created page as a dict.
        """
        page_id = uuid4()

        insert_stmt = self.pages_table.insert().values(
            id=page_id,
            session_id=session_id,
            page_type=page_type,
            viewport=viewport,
            status=status,
            load_timings=load_timings or {},
            low_confidence_reasons=low_confidence_reasons or [],
        )

        self.session.execute(insert_stmt)
        self.session.flush()

        # Fetch the created row
        select_stmt = select(self.pages_table).where(self.pages_table.c.id == page_id)
        row = self.session.execute(select_stmt).one()
        return dict(row._mapping)

    def page_exists(
        self,
        session_id: UUID,
        page_type: str,
        viewport: str,
    ) -> bool:
        """
        Check if a page with the given session_id, page_type, and viewport exists.

        Used for idempotency checks.
        """
        stmt = select(self.pages_table).where(
            self.pages_table.c.session_id == session_id,
            self.pages_table.c.page_type == page_type,
            self.pages_table.c.viewport == viewport,
        )
        result = self.session.execute(stmt).first()
        return result is not None

    def create_log(
        self,
        *,
        session_id: UUID,
        level: str,
        event_type: str,
        message: str,
        details: Optional[dict] = None,
    ) -> dict:
        """
        Create a crawl log entry.

        Returns the created log as a dict.
        """
        insert_stmt = (
            self.logs_table.insert()
            .values(
                session_id=session_id,
                level=level,
                event_type=event_type,
                message=message,
                details=details or {},
            )
            .returning(self.logs_table.c.id)
        )

        result = self.session.execute(insert_stmt).one()
        self.session.flush()

        log_id = result[0]
        row = self.session.execute(
            select(self.logs_table).where(self.logs_table.c.id == log_id)
        ).one()
        return dict(row._mapping)

    def create_artifact(
        self,
        *,
        session_id: UUID,
        page_id: Optional[UUID] = None,
        artifact_type: str,
        storage_uri: str,
        size_bytes: int,
        retention_until: Optional[datetime] = None,
        checksum: Optional[str] = None,
    ) -> dict:
        """
        Create an artifact record.

        page_id is optional for session-level artifacts (e.g. session_logs_jsonl).
        Returns the created artifact as a dict.
        """
        from uuid import uuid4

        artifact_id = uuid4()

        insert_stmt = self.artifacts_table.insert().values(
            id=artifact_id,
            session_id=session_id,
            page_id=page_id,
            type=artifact_type,
            storage_uri=storage_uri,
            size_bytes=size_bytes,
            retention_until=retention_until,
            checksum=checksum,
        )

        self.session.execute(insert_stmt)
        self.session.flush()

        # Fetch the created row
        select_stmt = select(self.artifacts_table).where(self.artifacts_table.c.id == artifact_id)
        row = self.session.execute(select_stmt).one()
        return dict(row._mapping)

    def get_expired_html_artifacts(self, batch_size: int) -> list[dict]:
        """
        Get expired html_gz artifacts not yet marked deleted.

        Returns list of dicts with id, session_id, storage_uri, size_bytes (and other columns).
        Ordered by retention_until ASC. Limited to batch_size.
        """
        t = self.artifacts_table
        stmt = (
            select(t)
            .where(
                and_(
                    t.c.type == "html_gz",
                    t.c.retention_until != None,  # noqa: E711
                    t.c.retention_until < func.now(),
                    t.c.deleted_at == None,  # noqa: E711
                )
            )
            .order_by(t.c.retention_until.asc())
            .limit(batch_size)
        )
        results = self.session.execute(stmt).all()
        return [dict(row._mapping) for row in results]

    def mark_artifact_deleted(self, artifact_id: UUID) -> None:
        """Set deleted_at to now for the given artifact (soft delete)."""
        now = datetime.now(timezone.utc)
        stmt = (
            self.artifacts_table.update()
            .where(self.artifacts_table.c.id == artifact_id)
            .values(deleted_at=now)
        )
        self.session.execute(stmt)
        self.session.flush()

    def update_page(
        self,
        page_id: UUID,
        *,
        status: Optional[str] = None,
        load_timings: Optional[dict] = None,
        low_confidence_reasons: Optional[list[str]] = None,
    ) -> None:
        """
        Update an audit page record.

        Updates only the provided fields.

        Note: low_confidence is not stored as a column on audit_pages;
        it can be derived from low_confidence_reasons (non-empty = low confidence).
        """
        update_values = {}
        if status is not None:
            update_values["status"] = status
        if load_timings is not None:
            update_values["load_timings"] = load_timings
        if low_confidence_reasons is not None:
            update_values["low_confidence_reasons"] = low_confidence_reasons

        if not update_values:
            return

        update_stmt = (
            self.pages_table.update()
            .where(self.pages_table.c.id == page_id)
            .values(**update_values)
        )
        self.session.execute(update_stmt)
        self.session.flush()

    def get_page_by_session_type_viewport(
        self,
        session_id: UUID,
        page_type: str,
        viewport: str,
    ) -> Optional[dict]:
        """
        Get a page by session_id, page_type, and viewport.

        Returns the page as a dict, or None if not found.
        """
        stmt = select(self.pages_table).where(
            self.pages_table.c.session_id == session_id,
            self.pages_table.c.page_type == page_type,
            self.pages_table.c.viewport == viewport,
        )
        result = self.session.execute(stmt).first()
        if result is None:
            return None
        return dict(result._mapping)

    def has_prior_sessions(self, url: str, exclude_session_id: Optional[UUID] = None) -> bool:
        """
        Check if there are prior sessions for the same normalized domain or URL.

        Args:
            url: The normalized URL to check
            exclude_session_id: Optional session ID to exclude from the check
                (useful when checking for prior sessions excluding the current one)

        Returns:
            True if prior sessions exist, False otherwise
            (i.e., first_time = not has_prior_sessions).
        """
        parsed = urlparse(url)
        domain = parsed.netloc.lower() if parsed.netloc else None

        if not domain:
            # If we can't extract a domain, fall back to exact URL match
            stmt = select(self.sessions_table).where(self.sessions_table.c.url == url)
            if exclude_session_id:
                stmt = stmt.where(self.sessions_table.c.id != exclude_session_id)
            result = self.session.execute(stmt).first()
            return result is not None

        # Check for prior sessions with same domain or exact URL match
        # Since URLs are normalized, we can check:
        # 1. Exact URL match
        # 2. Domain match (URL starts with http://domain or https://domain)

        # Build condition: exact URL match OR domain match (http or https)
        stmt = select(self.sessions_table).where(
            or_(
                self.sessions_table.c.url == url,
                self.sessions_table.c.url.like(f"http://{domain}%"),
                self.sessions_table.c.url.like(f"https://{domain}%"),
            )
        )
        if exclude_session_id:
            stmt = stmt.where(self.sessions_table.c.id != exclude_session_id)

        result = self.session.execute(stmt).first()
        return result is not None

    def update_session_low_confidence(
        self,
        session_id: UUID,
        low_confidence: bool,
    ) -> None:
        """
        Update the low_confidence flag on an audit session.

        Args:
            session_id: The session ID to update
            low_confidence: The low_confidence value to set
        """
        update_stmt = (
            self.sessions_table.update()
            .where(self.sessions_table.c.id == session_id)
            .values(low_confidence=low_confidence)
        )
        self.session.execute(update_stmt)
        self.session.flush()

    def update_session_pdp_url(
        self,
        session_id: UUID,
        pdp_url: Optional[str],
    ) -> None:
        """
        Update the pdp_url on an audit session (selected PDP from discovery).

        Args:
            session_id: The session ID to update
            pdp_url: The selected PDP URL, or None if not found
        """
        update_stmt = (
            self.sessions_table.update()
            .where(self.sessions_table.c.id == session_id)
            .values(pdp_url=pdp_url)
        )
        self.session.execute(update_stmt)
        self.session.flush()

    def create_question(
        self,
        *,
        key: str,
        stage: str,
        category: str,
        page_type: str,
        narrative_tier: int,
        baseline_severity: int,
        question_text: str,
        allowed_evidence_types: list[str],
        ruleset_version: str = "v1",
        fix_intent: Optional[str] = None,
        specific_example_fix_text: Optional[str] = None,
        pass_criteria: Optional[str] = None,
        fail_criteria: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """
        Create a new audit question.

        Returns the created question as a dict.
        """
        question_id = uuid4()
        now = datetime.now(timezone.utc)

        insert_stmt = self.questions_table.insert().values(
            id=question_id,
            key=key,
            stage=stage,
            category=category,
            page_type=page_type,
            narrative_tier=narrative_tier,
            baseline_severity=baseline_severity,
            fix_intent=fix_intent,
            specific_example_fix_text=specific_example_fix_text,
            question_text=question_text,
            pass_criteria=pass_criteria,
            fail_criteria=fail_criteria,
            notes=notes,
            allowed_evidence_types=allowed_evidence_types,
            ruleset_version=ruleset_version,
            created_at=now,
            updated_at=now,
        )

        self.session.execute(insert_stmt)
        self.session.flush()

        select_stmt = select(self.questions_table).where(self.questions_table.c.id == question_id)
        row = self.session.execute(select_stmt).one()
        return dict(row._mapping)

    def get_question_by_id(self, question_id: UUID) -> Optional[dict]:
        """
        Get an audit question by ID.

        Returns the question as a dict, or None if not found.
        """
        stmt = select(self.questions_table).where(self.questions_table.c.id == question_id)
        result = self.session.execute(stmt).first()
        if result is None:
            return None
        return dict(result._mapping)

    def get_question_by_key(self, key: str) -> Optional[dict]:
        """
        Get an audit question by key.

        Returns the question as a dict, or None if not found.
        """
        stmt = select(self.questions_table).where(self.questions_table.c.key == key)
        result = self.session.execute(stmt).first()
        if result is None:
            return None
        return dict(result._mapping)

    def list_questions(
        self,
        *,
        stage: Optional[str] = None,
        page_type: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[dict]:
        """
        List audit questions with optional filters.

        Returns a list of question dicts.
        """
        stmt = select(self.questions_table)
        conditions = []
        if stage is not None:
            conditions.append(self.questions_table.c.stage == stage)
        if page_type is not None:
            conditions.append(self.questions_table.c.page_type == page_type)
        if category is not None:
            conditions.append(self.questions_table.c.category == category)

        if conditions:
            stmt = stmt.where(and_(*conditions))

        stmt = stmt.order_by(self.questions_table.c.created_at.desc())
        results = self.session.execute(stmt).all()
        return [dict(row._mapping) for row in results]

    def update_question(
        self,
        question_id: UUID,
        *,
        stage: Optional[str] = None,
        category: Optional[str] = None,
        page_type: Optional[str] = None,
        narrative_tier: Optional[int] = None,
        baseline_severity: Optional[int] = None,
        fix_intent: Optional[str] = None,
        specific_example_fix_text: Optional[str] = None,
        question_text: Optional[str] = None,
        pass_criteria: Optional[str] = None,
        fail_criteria: Optional[str] = None,
        notes: Optional[str] = None,
        allowed_evidence_types: Optional[list[str]] = None,
        ruleset_version: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Update an audit question.

        Updates only the provided fields. Returns the updated question as a dict,
        or None if not found.
        """
        update_values = {}
        if stage is not None:
            update_values["stage"] = stage
        if category is not None:
            update_values["category"] = category
        if page_type is not None:
            update_values["page_type"] = page_type
        if narrative_tier is not None:
            update_values["narrative_tier"] = narrative_tier
        if baseline_severity is not None:
            update_values["baseline_severity"] = baseline_severity
        if fix_intent is not None:
            update_values["fix_intent"] = fix_intent
        if specific_example_fix_text is not None:
            update_values["specific_example_fix_text"] = specific_example_fix_text
        if question_text is not None:
            update_values["question_text"] = question_text
        if pass_criteria is not None:
            update_values["pass_criteria"] = pass_criteria
        if fail_criteria is not None:
            update_values["fail_criteria"] = fail_criteria
        if notes is not None:
            update_values["notes"] = notes
        if allowed_evidence_types is not None:
            update_values["allowed_evidence_types"] = allowed_evidence_types
        if ruleset_version is not None:
            update_values["ruleset_version"] = ruleset_version

        if not update_values:
            return self.get_question_by_id(question_id)

        update_values["updated_at"] = datetime.now(timezone.utc)

        update_stmt = (
            self.questions_table.update()
            .where(self.questions_table.c.id == question_id)
            .values(**update_values)
        )
        self.session.execute(update_stmt)
        self.session.flush()

        return self.get_question_by_id(question_id)

    def delete_question(self, question_id: UUID) -> bool:
        """
        Delete an audit question by ID.

        Returns True if deleted, False if not found.
        """
        question = self.get_question_by_id(question_id)
        if question is None:
            return False

        delete_stmt = self.questions_table.delete().where(self.questions_table.c.id == question_id)
        self.session.execute(delete_stmt)
        self.session.flush()
        return True

    def get_question_results_by_audit_id(self, audit_id: UUID) -> list[dict]:
        """
        Get all question results for an audit session.

        Returns a list of result dicts.
        """
        stmt = select(self.question_results_table).where(
            self.question_results_table.c.audit_id == audit_id
        )
        stmt = stmt.order_by(self.question_results_table.c.created_at.desc())
        results = self.session.execute(stmt).all()
        return [dict(row._mapping) for row in results]

    def get_question_results_by_question_id(self, question_id: UUID) -> list[dict]:
        """
        Get all results for a specific question across all audits.

        Returns a list of result dicts.
        """
        stmt = select(self.question_results_table).where(
            self.question_results_table.c.question_id == question_id
        )
        stmt = stmt.order_by(self.question_results_table.c.created_at.desc())
        results = self.session.execute(stmt).all()
        return [dict(row._mapping) for row in results]

    def get_question_result(self, result_id: UUID) -> Optional[dict]:
        """
        Get a question result by ID.

        Returns the result as a dict, or None if not found.
        """
        stmt = select(self.question_results_table).where(
            self.question_results_table.c.id == result_id
        )
        result = self.session.execute(stmt).first()
        if result is None:
            return None
        return dict(result._mapping)
