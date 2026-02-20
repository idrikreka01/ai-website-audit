"""Add functional flow flags to audit_sessions table."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_add_functional_flow"
down_revision: Union[str, None] = "0013_add_page_coverage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_sessions",
        sa.Column("functional_flow_score", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "audit_sessions",
        sa.Column(
            "functional_flow_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.create_check_constraint(
        "ck_audit_sessions_functional_flow_score",
        "audit_sessions",
        "functional_flow_score >= 0 AND functional_flow_score <= 3",
    )


def downgrade() -> None:
    op.drop_constraint("ck_audit_sessions_functional_flow_score", "audit_sessions", type_="check")
    op.drop_column("audit_sessions", "functional_flow_details")
    op.drop_column("audit_sessions", "functional_flow_score")
