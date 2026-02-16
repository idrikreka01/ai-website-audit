"""Add page coverage flags to audit_sessions table."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_add_page_coverage"
down_revision: Union[str, None] = "0012_normalize_page_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_sessions",
        sa.Column("homepage_ok", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "audit_sessions",
        sa.Column("pdp_ok", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "audit_sessions",
        sa.Column("cart_ok", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "audit_sessions",
        sa.Column("checkout_ok", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "audit_sessions",
        sa.Column("page_coverage_score", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_audit_sessions_page_coverage_score",
        "audit_sessions",
        "page_coverage_score >= 0 AND page_coverage_score <= 4",
    )


def downgrade() -> None:
    op.drop_constraint("ck_audit_sessions_page_coverage_score", "audit_sessions", type_="check")
    op.drop_column("audit_sessions", "page_coverage_score")
    op.drop_column("audit_sessions", "checkout_ok")
    op.drop_column("audit_sessions", "cart_ok")
    op.drop_column("audit_sessions", "pdp_ok")
    op.drop_column("audit_sessions", "homepage_ok")
