"""Add navigation, collection, and 404 page types to audit_questions."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0021_add_new_page_types"
down_revision: Union[str, None] = "0020_add_unknown_result"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_audit_questions_page_type", "audit_questions", type_="check")
    op.create_check_constraint(
        "ck_audit_questions_page_type",
        "audit_questions",
        "page_type IN ('homepage', 'product', 'cart', 'checkout', 'navigation', 'collection', '404')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_audit_questions_page_type", "audit_questions", type_="check")
    op.execute("DELETE FROM audit_questions WHERE page_type IN ('navigation', 'collection', '404')")
    op.create_check_constraint(
        "ck_audit_questions_page_type",
        "audit_questions",
        "page_type IN ('homepage', 'product', 'cart', 'checkout')",
    )
