"""Add audit_sessions.pdp_url (Task 07 — PDP discovery)."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_audit_sessions_pdp_url"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_sessions",
        sa.Column("pdp_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audit_sessions", "pdp_url")
