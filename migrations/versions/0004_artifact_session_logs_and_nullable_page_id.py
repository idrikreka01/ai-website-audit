"""Add session_logs_jsonl artifact type and make artifacts.page_id nullable (TECH_SPEC v1.20).

Upgrade: extends artifact_type_enum (no existing data change), makes page_id nullable.
Downgrade: reverts page_id to NOT NULL; enum value is not removed (PostgreSQL limitation).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_session_logs_null_page_id"
down_revision: Union[str, None] = "0003_add_artifacts_deleted_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Allow session-level artifacts (e.g. session_logs_jsonl) with no page.
    op.alter_column(
        "artifacts",
        "page_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    # Add new artifact type for exported session logs (TECH_SPEC v1.20).
    op.execute("ALTER TYPE artifact_type_enum ADD VALUE IF NOT EXISTS 'session_logs_jsonl'")


def downgrade() -> None:
    # Revert page_id to NOT NULL (fails if any NULL page_id rows exist).
    op.alter_column(
        "artifacts",
        "page_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    # PostgreSQL does not support removing an enum value; leave session_logs_jsonl in the type.
    # If you must remove it, recreate the enum and column (data migration required).
    pass
