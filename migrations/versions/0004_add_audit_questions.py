"""Add audit_questions and audit_question_results tables for Sprint 2."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_add_audit_questions"
down_revision: Union[str, None] = "0003_add_artifacts_deleted_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("page_type", sa.Text(), nullable=False),
        sa.Column("narrative_tier", sa.Integer(), nullable=False),
        sa.Column("baseline_severity", sa.Integer(), nullable=False),
        sa.Column("fix_intent", sa.Text(), nullable=True),
        sa.Column("specific_example_fix_text", sa.Text(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("pass_criteria", sa.Text(), nullable=True),
        sa.Column("fail_criteria", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "allowed_evidence_types",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("ruleset_version", sa.Text(), nullable=False, server_default="v1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stage IN ('awareness', 'consideration', 'conversion')",
            name="ck_audit_questions_stage",
        ),
        sa.CheckConstraint(
            "page_type IN ('homepage', 'collection', 'product', 'cart', 'checkout')",
            name="ck_audit_questions_page_type",
        ),
        sa.CheckConstraint(
            "narrative_tier IN (1, 2, 3)",
            name="ck_audit_questions_narrative_tier",
        ),
        sa.CheckConstraint(
            "baseline_severity >= 1 AND baseline_severity <= 5",
            name="ck_audit_questions_baseline_severity",
        ),
    )

    op.create_table(
        "audit_question_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pass_fail", sa.Boolean(), nullable=False),
        sa.Column("score_1_to_10", sa.Integer(), nullable=False),
        sa.Column("evidence_source_type", sa.Text(), nullable=False),
        sa.Column("payload_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ai_reasoning_summary", sa.Text(), nullable=True),
        sa.Column("ai_confidence_1_to_10", sa.Integer(), nullable=True),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.Column("ruleset_version", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["audit_questions.id"],
            name="fk_audit_question_results_question_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["audit_id"],
            ["audit_sessions.id"],
            name="fk_audit_question_results_audit_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "score_1_to_10 >= 1 AND score_1_to_10 <= 10",
            name="ck_audit_question_results_score",
        ),
        sa.CheckConstraint(
            "evidence_source_type IN ('html_safe', 'screenshot_only', 'mixed')",
            name="ck_audit_question_results_evidence_source_type",
        ),
        sa.CheckConstraint(
            "(ai_confidence_1_to_10 IS NULL) OR (ai_confidence_1_to_10 >= 1 AND ai_confidence_1_to_10 <= 10)",
            name="ck_audit_question_results_ai_confidence",
        ),
        sa.UniqueConstraint(
            "audit_id", "question_id", name="uq_audit_question_results_audit_question"
        ),
    )

    op.create_index(
        "ix_audit_questions_stage_page_type_category",
        "audit_questions",
        ["stage", "page_type", "category"],
    )
    op.create_index(
        "ix_audit_question_results_audit_id",
        "audit_question_results",
        ["audit_id"],
    )
    op.create_index(
        "ix_audit_question_results_question_id",
        "audit_question_results",
        ["question_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_question_results_question_id", table_name="audit_question_results")
    op.drop_index("ix_audit_question_results_audit_id", table_name="audit_question_results")
    op.drop_index("ix_audit_questions_stage_page_type_category", table_name="audit_questions")
    op.drop_table("audit_question_results")
    op.drop_table("audit_questions")


# Example INSERT statements:
#
# INSERT INTO audit_questions (
#     key, stage, category, page_type, narrative_tier, baseline_severity,
#     question_text, allowed_evidence_types, ruleset_version
# ) VALUES (
#     'aw_headline_clear_offer',
#     'awareness',
#     'headline_clarity',
#     'homepage',
#     1,
#     3,
#     'Is the headline clear about the value proposition?',
#     ARRAY['dom', 'screenshot', 'visible_text']::text[],
#     'v1'
# );
#
# INSERT INTO audit_question_results (
#     audit_id, question_id, pass_fail, score_1_to_10, evidence_source_type,
#     payload_ref, ai_reasoning_summary, ai_confidence_1_to_10, model_version, ruleset_version
# ) VALUES (
#     '123e4567-e89b-12d3-a456-426614174000'::uuid,
#     '223e4567-e89b-12d3-a456-426614174000'::uuid,
#     true,
#     8,
#     'mixed',
#     '{"dom_payload_id": "323e4567-e89b-12d3-a456-426614174000", "screenshot_id": "423e4567-e89b-12d3-a456-426614174000", "page_type": "homepage"}'::jsonb,
#     'Headline clearly states the value proposition with strong call-to-action.',
#     9,
#     'gpt-4o',
#     'v1'
# );
