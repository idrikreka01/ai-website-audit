"""Normalize page_type values in audit_questions table."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0012_normalize_page_types"
down_revision: Union[str, None] = "0011_add_confidence_score"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE audit_questions
        SET page_type = 'cart'
        WHERE page_type IN ('cart page', 'CART PAGE', 'Cart Page', 'CART', 'Cart');
    """)
    
    op.execute("""
        UPDATE audit_questions
        SET page_type = 'product'
        WHERE page_type IN ('product page', 'PRODUCT PAGE', 'Product Page', 'pdp', 'PDP', 'PRODUCT', 'product');
    """)
    
    op.execute("""
        UPDATE audit_questions
        SET page_type = 'checkout'
        WHERE page_type IN ('checkout page', 'CHECKOUT PAGE', 'Checkout Page', 'CHECKOUT');
    """)
    
    op.execute("""
        UPDATE audit_questions
        SET page_type = 'homepage'
        WHERE page_type IN ('home page', 'HOME PAGE', 'Home Page', 'HOME', 'Home', 'landing', 'LANDING');
    """)


def downgrade() -> None:
    pass
