"""add question never-repeat dedupe tables

Revision ID: 0008_never_repeat
Revises: 0007_source_question
Create Date: 2026-06-24
"""

from __future__ import annotations

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008_never_repeat"
down_revision = "0007_source_question"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.drop_constraint(
        "uq_question_fingerprint_normalized_hash",
        "question_fingerprint",
        type_="unique",
    )
    op.add_column(
        "question_fingerprint",
        sa.Column("prompt_embedding", Vector(1024), nullable=True),
    )
    op.add_column(
        "question_fingerprint",
        sa.Column("summary_embedding", Vector(1024), nullable=True),
    )
    op.add_column(
        "question_fingerprint",
        sa.Column("decision_embedding", Vector(1024), nullable=True),
    )
    op.add_column(
        "question_fingerprint",
        sa.Column("answer_skeleton_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "question_fingerprint",
        sa.Column(
            "dedupe_decision_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column("question_fingerprint", "dedupe_decision_json", server_default=None)

    op.create_table(
        "question_dedupe_check",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_bundle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_hash", sa.String(length=64), nullable=False),
        sa.Column("normalized_hash", sa.String(length=64), nullable=False),
        sa.Column("template_family", sa.String(length=128), nullable=False),
        sa.Column("source_event_id", sa.String(length=128), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("rejection_level", sa.String(length=32), nullable=True),
        sa.Column("max_similarity", sa.Float(), nullable=True),
        sa.Column("structure_change_count", sa.Integer(), nullable=True),
        sa.Column("matched_question_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("decision_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('PASS', 'REJECT')",
            name="ck_question_dedupe_check_decision",
        ),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_bundle_id"], ["source_bundle.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_question_dedupe_check_question_id",
        "question_dedupe_check",
        ["question_id"],
    )
    op.create_index(
        "ix_question_dedupe_check_user_created",
        "question_dedupe_check",
        ["user_id", "created_at"],
    )

    op.create_table(
        "question_template_denylist",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_family", sa.String(length=128), nullable=False),
        sa.Column("trigger_question_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trigger_question_id"], ["question.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "template_family", name="uq_question_template_deny_user_family"),
    )
    op.create_index("ix_question_template_deny_user", "question_template_denylist", ["user_id"])

    op.create_table(
        "question_duplicate_complaint",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("similar_question_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("duplicate_type", sa.String(length=32), nullable=False),
        sa.Column("template_family", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "duplicate_type IN ("
            "'text', 'semantic', 'parameter', 'role', 'structure', "
            "'answer_skeleton', 'same_event', 'other'"
            ")",
            name="ck_question_duplicate_complaint_type",
        ),
        sa.CheckConstraint(
            "status IN ('ACCEPTED')",
            name="ck_question_duplicate_complaint_status",
        ),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["training_session.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["similar_question_id"], ["question.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "session_id", name="uq_question_duplicate_complaint_session"),
    )
    op.create_index(
        "ix_question_duplicate_complaint_user_created",
        "question_duplicate_complaint",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_question_duplicate_complaint_user_created",
        table_name="question_duplicate_complaint",
    )
    op.drop_table("question_duplicate_complaint")
    op.drop_index("ix_question_template_deny_user", table_name="question_template_denylist")
    op.drop_table("question_template_denylist")
    op.drop_index("ix_question_dedupe_check_user_created", table_name="question_dedupe_check")
    op.drop_index("ix_question_dedupe_check_question_id", table_name="question_dedupe_check")
    op.drop_table("question_dedupe_check")
    op.drop_column("question_fingerprint", "dedupe_decision_json")
    op.drop_column("question_fingerprint", "answer_skeleton_hash")
    op.drop_column("question_fingerprint", "decision_embedding")
    op.drop_column("question_fingerprint", "summary_embedding")
    op.drop_column("question_fingerprint", "prompt_embedding")
    op.create_unique_constraint(
        "uq_question_fingerprint_normalized_hash",
        "question_fingerprint",
        ["normalized_hash"],
    )
