"""add source-backed question preparation tables

Revision ID: 0007_source_question
Revises: 0006_defect_memory
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_source_question"
down_revision = "0006_defect_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_bundle",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("target_defects", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("search_queries", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("highest_source_level", sa.String(length=1), nullable=True),
        sa.Column("credential", sa.String(length=64), nullable=False),
        sa.Column("prompt_versions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'READY', 'INVALID')",
            name="ck_source_bundle_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential", name="uq_source_bundle_credential"),
    )
    op.create_index("ix_source_bundle_user_status", "source_bundle", ["user_id", "status"])

    op.create_table(
        "question_source",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_bundle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("publisher", sa.String(length=256), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("level", sa.String(length=1), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "accessed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("extracted_characters", sa.Integer(), nullable=False),
        sa.Column("fetch_status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("level IN ('S', 'A', 'B', 'C')", name="ck_question_source_level"),
        sa.ForeignKeyConstraint(["source_bundle_id"], ["source_bundle.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_bundle_id", "url", name="uq_question_source_bundle_url"),
    )

    op.create_table(
        "source_claim",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("locator", sa.String(length=256), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("support_status", sa.String(length=16), nullable=False),
        sa.Column("verifier_reason", sa.Text(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "support_status IN ('VERIFIED', 'CONFLICTED', 'UNSUPPORTED')",
            name="ck_source_claim_support_status",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["question_source.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_claim_source_status", "source_claim", ["source_id", "support_status"])

    op.create_table(
        "question",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_bundle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("target_defects", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("exposed_count", sa.Integer(), nullable=False),
        sa.Column("unsupported_claim_count", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("expected_reasoning_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "prohibited_inferences_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "hypothetical_assumptions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exposed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'VERIFIED', 'DEDUPED', 'READY', 'EXPOSED', "
            "'RETIRED', 'INVALID')",
            name="ck_question_status",
        ),
        sa.ForeignKeyConstraint(["source_bundle_id"], ["source_bundle.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_question_user_status", "question", ["user_id", "status"])

    op.create_table(
        "question_claim_map",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usage_type", sa.String(length=32), nullable=False),
        sa.Column("sentence_index", sa.Integer(), nullable=False),
        sa.Column("sentence_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["source_claim.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_id",
            "claim_id",
            "sentence_index",
            "usage_type",
            name="uq_question_claim_map_fact",
        ),
    )

    op.create_table(
        "question_fingerprint",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_hash", sa.String(length=64), nullable=False),
        sa.Column("structural_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("template_family", sa.String(length=128), nullable=False),
        sa.Column("source_event_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_hash", name="uq_question_fingerprint_normalized_hash"),
        sa.UniqueConstraint("question_id", name="uq_question_fingerprint_question_id"),
    )

    op.alter_column(
        "question_rubric",
        "training_session_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_question_rubric_question_id_question",
        "question_rubric",
        "question",
        ["question_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_question_rubric_question_version",
        "question_rubric",
        ["question_id", "version"],
    )
    op.execute("UPDATE training_session SET question_id = NULL WHERE question_id IS NOT NULL")
    op.create_foreign_key(
        "fk_training_session_question_id_question",
        "training_session",
        "question",
        ["question_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.execute("UPDATE training_session SET question_id = NULL")
    op.execute("DELETE FROM question_rubric WHERE training_session_id IS NULL")
    op.drop_constraint(
        "fk_training_session_question_id_question",
        "training_session",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_question_rubric_question_version",
        "question_rubric",
        type_="unique",
    )
    op.drop_constraint(
        "fk_question_rubric_question_id_question",
        "question_rubric",
        type_="foreignkey",
    )
    op.alter_column(
        "question_rubric",
        "training_session_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.drop_table("question_fingerprint")
    op.drop_table("question_claim_map")
    op.drop_index("ix_question_user_status", table_name="question")
    op.drop_table("question")
    op.drop_index("ix_source_claim_source_status", table_name="source_claim")
    op.drop_table("source_claim")
    op.drop_table("question_source")
    op.drop_index("ix_source_bundle_user_status", table_name="source_bundle")
    op.drop_table("source_bundle")
