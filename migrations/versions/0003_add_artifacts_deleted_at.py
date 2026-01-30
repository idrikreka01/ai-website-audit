"""Add artifacts.deleted_at for retention cleanup (RETENTION_ENFORCEMENT.md)."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_add_artifacts_deleted_at"
down_revision: Union[str, None] = "0002_add_audit_sessions_pdp_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "artifacts",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("artifacts", "deleted_at")
