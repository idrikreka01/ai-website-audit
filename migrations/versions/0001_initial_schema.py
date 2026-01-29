from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enums ---
    audit_session_status_enum = sa.Enum(
        "queued",
        "running",
        "completed",
        "failed",
        "partial",
        name="audit_session_status_enum",
    )
    audit_mode_enum = sa.Enum(
        "standard",
        "debug",
        "evidence_pack",
        name="audit_mode_enum",
    )
    retention_policy_enum = sa.Enum(
        "standard",
        "short",
        "long",
        name="retention_policy_enum",
    )
    page_type_enum = sa.Enum(
        "homepage",
        "pdp",
        name="page_type_enum",
    )
    viewport_enum = sa.Enum(
        "desktop",
        "mobile",
        name="viewport_enum",
    )
    page_status_enum = sa.Enum(
        "ok",
        "failed",
        "pending",
        name="page_status_enum",
    )
    artifact_type_enum = sa.Enum(
        "screenshot",
        "visible_text",
        "features_json",
        "html_gz",
        name="artifact_type_enum",
    )
    log_level_enum = sa.Enum(
        "info",
        "warn",
        "error",
        name="log_level_enum",
    )
    event_type_enum = sa.Enum(
        "navigation",
        "popup",
        "retry",
        "timeout",
        "error",
        "artifact",
        name="event_type_enum",
    )

    # --- Tables ---
    op.create_table(
        "audit_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", audit_session_status_enum, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("mode", audit_mode_enum, nullable=False),
        sa.Column("retention_policy", retention_policy_enum, nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("crawl_policy_version", sa.Text(), nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("low_confidence", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    op.create_table(
        "audit_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_type", page_type_enum, nullable=False),
        sa.Column("viewport", viewport_enum, nullable=False),
        sa.Column("status", page_status_enum, nullable=False),
        sa.Column("load_timings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "low_confidence_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["audit_sessions.id"],
            name="fk_audit_pages_session_id",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", artifact_type_enum, nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checksum", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["audit_sessions.id"],
            name="fk_artifacts_session_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["audit_pages.id"],
            name="fk_artifacts_page_id",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "crawl_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("level", log_level_enum, nullable=False),
        sa.Column("event_type", event_type_enum, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["audit_sessions.id"],
            name="fk_crawl_logs_session_id",
            ondelete="CASCADE",
        ),
    )

    # --- Indexes (per TECH_SPEC) ---
    op.create_index(
        "ix_audit_sessions_status_created_at",
        "audit_sessions",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_audit_sessions_crawl_policy_version",
        "audit_sessions",
        ["crawl_policy_version"],
    )
    op.create_index(
        "ix_audit_pages_session_page_viewport",
        "audit_pages",
        ["session_id", "page_type", "viewport"],
    )
    op.create_index(
        "ix_artifacts_session_type",
        "artifacts",
        ["session_id", "type"],
    )
    op.create_index(
        "ix_crawl_logs_session_timestamp",
        "crawl_logs",
        ["session_id", "timestamp"],
    )


def downgrade() -> None:
    # Drop indexes first.
    op.drop_index("ix_crawl_logs_session_timestamp", table_name="crawl_logs")
    op.drop_index("ix_artifacts_session_type", table_name="artifacts")
    op.drop_index("ix_audit_pages_session_page_viewport", table_name="audit_pages")
    op.drop_index("ix_audit_sessions_crawl_policy_version", table_name="audit_sessions")
    op.drop_index("ix_audit_sessions_status_created_at", table_name="audit_sessions")

    # Drop tables.
    op.drop_table("crawl_logs")
    op.drop_table("artifacts")
    op.drop_table("audit_pages")
    op.drop_table("audit_sessions")

    # Drop enums.
    bind = op.get_bind()
    for enum_name in [
        "event_type_enum",
        "log_level_enum",
        "artifact_type_enum",
        "page_status_enum",
        "viewport_enum",
        "page_type_enum",
        "retention_policy_enum",
        "audit_mode_enum",
        "audit_session_status_enum",
    ]:
        postgresql.ENUM(name=enum_name).drop(bind, checkfirst=True)
