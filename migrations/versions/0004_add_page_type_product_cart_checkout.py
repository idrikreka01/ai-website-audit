"""Add product, cart, checkout to page_type_enum for UniversalEcomNavigator."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0004_add_ecom_page_types"
down_revision: Union[str, None] = "0003_add_artifacts_deleted_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for value in ("product", "cart", "checkout"):
        op.execute(
            f"DO $$ BEGIN ALTER TYPE page_type_enum ADD VALUE '{value}'; "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
        )


def downgrade() -> None:
    pass
