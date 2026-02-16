"""Add confidence_score column to audit_results table."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_add_confidence_score"
down_revision: Union[str, None] = "0010_replace_questions_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_results",
        sa.Column("confidence_score", sa.Integer(), nullable=True),
    )
    
    op.execute("UPDATE audit_results SET confidence_score = 5 WHERE confidence_score IS NULL")
    
    op.alter_column("audit_results", "confidence_score", nullable=False)
    
    op.create_check_constraint(
        "ck_audit_results_confidence_score",
        "audit_results",
        "confidence_score >= 1 AND confidence_score <= 10",
    )


def downgrade() -> None:
    op.drop_constraint("ck_audit_results_confidence_score", "audit_results", type_="check")
    op.drop_column("audit_results", "confidence_score")
