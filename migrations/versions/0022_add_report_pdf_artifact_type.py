from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0022_add_report_pdf"
down_revision: Union[str, None] = "0021_add_new_page_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE artifact_type_enum ADD VALUE IF NOT EXISTS 'report_pdf'")


def downgrade() -> None:
    pass
