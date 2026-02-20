"""Add audit_storefront_report_cards table for storing AI-generated storefront report cards."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_add_storefront_report_cards"
down_revision: Union[str, None] = "0018_add_stage_summaries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_storefront_report_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("stage_descriptions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("final_thoughts", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["audit_sessions.id"],
            name="fk_audit_storefront_report_cards_session_id",
            ondelete="CASCADE",
        ),
    )
    
    op.create_index(
        "ix_audit_storefront_report_cards_session_id",
        "audit_storefront_report_cards",
        ["session_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_storefront_report_cards_session_id", table_name="audit_storefront_report_cards")
    op.drop_table("audit_storefront_report_cards")
