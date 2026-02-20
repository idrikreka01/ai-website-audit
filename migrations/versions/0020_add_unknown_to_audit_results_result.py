"""Add 'unknown' to audit_results.result check constraint."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_add_unknown_result"
down_revision: Union[str, None] = "0019_add_storefront_report_cards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_audit_results_result", "audit_results", type_="check")
    op.create_check_constraint(
        "ck_audit_results_result",
        "audit_results",
        "result IN ('pass', 'fail', 'unknown')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_audit_results_result", "audit_results", type_="check")
    op.execute("UPDATE audit_results SET result = 'fail' WHERE result = 'unknown'")
    op.create_check_constraint(
        "ck_audit_results_result",
        "audit_results",
        "result IN ('pass', 'fail')",
    )
