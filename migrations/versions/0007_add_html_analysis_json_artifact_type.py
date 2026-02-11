from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0007_add_html_analysis_json"
down_revision: Union[str, None] = "0006_html_analysis_event"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE artifact_type_enum ADD VALUE IF NOT EXISTS 'html_analysis_json'")


def downgrade() -> None:
    pass
