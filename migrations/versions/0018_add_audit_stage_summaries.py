"""Add audit_stage_summaries table for storing AI-generated stage summaries."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_add_stage_summaries"
down_revision: Union[str, None] = "0017_add_ai_audit_and_score"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_stage_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["audit_sessions.id"],
            name="fk_audit_stage_summaries_session_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "stage IN ('Awareness', 'Consideration', 'Conversion')",
            name="ck_audit_stage_summaries_stage",
        ),
    )

    op.create_index(
        "ix_audit_stage_summaries_session_id",
        "audit_stage_summaries",
        ["session_id"],
    )
    op.create_index(
        "ix_audit_stage_summaries_session_stage",
        "audit_stage_summaries",
        ["session_id", "stage"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_stage_summaries_session_stage", table_name="audit_stage_summaries")
    op.drop_index("ix_audit_stage_summaries_session_id", table_name="audit_stage_summaries")
    op.drop_table("audit_stage_summaries")
