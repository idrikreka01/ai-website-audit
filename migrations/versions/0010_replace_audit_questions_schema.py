"""Replace audit_questions schema and add audit_results table."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_replace_questions_schema"
down_revision: Union[str, None] = "0007_add_html_analysis_json"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing audit_question_results table first (if exists, due to FK)
    op.execute("DROP TABLE IF EXISTS audit_question_results CASCADE")
    
    # Drop existing audit_questions table (this will cascade delete question_results)
    op.execute("DROP TABLE IF EXISTS audit_questions CASCADE")
    
    # Drop indexes if they exist
    op.execute("DROP INDEX IF EXISTS ix_audit_questions_stage_page_type_category")
    op.execute("DROP INDEX IF EXISTS ix_audit_question_results_audit_id")
    op.execute("DROP INDEX IF EXISTS ix_audit_question_results_question_id")
    
    # Create new audit_questions table
    op.create_table(
        "audit_questions",
        sa.Column("question_id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("ai_criteria", sa.Text(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("bar_chart_category", sa.Text(), nullable=False),
        sa.Column("exact_fix", sa.Text(), nullable=False),
        sa.Column("page_type", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "tier >= 1 AND tier <= 3",
            name="ck_audit_questions_tier",
        ),
        sa.CheckConstraint(
            "severity >= 1 AND severity <= 5",
            name="ck_audit_questions_severity",
        ),
        sa.CheckConstraint(
            "page_type IN ('homepage', 'product', 'cart', 'checkout')",
            name="ck_audit_questions_page_type",
        ),
    )
    
    # Create audit_results table
    op.create_table(
        "audit_results",
        sa.Column("result_id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["audit_questions.question_id"],
            name="fk_audit_results_question_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "result IN ('pass', 'fail')",
            name="ck_audit_results_result",
        ),
    )
    
    # Create indexes
    op.create_index(
        "ix_audit_results_question_id",
        "audit_results",
        ["question_id"],
    )
    op.create_index(
        "ix_audit_results_session_id",
        "audit_results",
        ["session_id"],
    )


def downgrade() -> None:
    # Drop audit_results first (due to FK constraint)
    op.drop_index("ix_audit_results_session_id", table_name="audit_results")
    op.drop_index("ix_audit_results_question_id", table_name="audit_results")
    op.drop_table("audit_results")
    
    # Drop audit_questions
    op.drop_table("audit_questions")
    
    # Note: We don't recreate the old tables here as this is a schema replacement
    # If you need the old schema back, restore from a backup or create a new migration
