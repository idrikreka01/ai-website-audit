"""Add AI audit flags and overall score to audit_sessions table."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_add_ai_audit_and_score"
down_revision: Union[str, None] = "0015_add_functional_flow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_sessions",
        sa.Column("ai_audit_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "audit_sessions",
        sa.Column("ai_audit_flag", sa.Text(), nullable=True),
    )
    op.add_column(
        "audit_sessions",
        sa.Column("overall_score_percentage", sa.Float(), nullable=True),
    )
    op.add_column(
        "audit_sessions",
        sa.Column("needs_manual_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_check_constraint(
        "ck_audit_sessions_ai_audit_score",
        "audit_sessions",
        "ai_audit_score IS NULL OR (ai_audit_score >= 0 AND ai_audit_score <= 1)",
    )
    op.create_check_constraint(
        "ck_audit_sessions_ai_audit_flag",
        "audit_sessions",
        "ai_audit_flag IS NULL OR ai_audit_flag IN ('high', 'medium', 'low')",
    )
    op.create_check_constraint(
        "ck_audit_sessions_overall_score_percentage",
        "audit_sessions",
        "overall_score_percentage IS NULL OR (overall_score_percentage >= 0 AND overall_score_percentage <= 100)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_audit_sessions_overall_score_percentage", "audit_sessions", type_="check")
    op.drop_constraint("ck_audit_sessions_ai_audit_flag", "audit_sessions", type_="check")
    op.drop_constraint("ck_audit_sessions_ai_audit_score", "audit_sessions", type_="check")
    op.drop_column("audit_sessions", "needs_manual_review")
    op.drop_column("audit_sessions", "overall_score_percentage")
    op.drop_column("audit_sessions", "ai_audit_flag")
    op.drop_column("audit_sessions", "ai_audit_score")
