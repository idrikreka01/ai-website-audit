"""Merge three 0004 migration branches into single head."""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "0005_merge_0004_branches"
down_revision: Union[str, tuple[str, ...], None] = (
    "0004_add_audit_questions",
    "0004_add_ecom_page_types",
    "0004_session_logs_null_page_id",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
