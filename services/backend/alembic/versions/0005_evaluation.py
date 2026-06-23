"""add evidence based evaluation tables

Revision ID: 0005_evaluation
Revises: 0004_transcription_metrics
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_evaluation"
down_revision = "0004_transcription_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_rubric",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("training_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("dimensions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "expected_elements_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("fatal_omissions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "frozen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["training_session_id"], ["training_session.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "training_session_id",
            "version",
            name="uq_question_rubric_session_version",
        ),
    )
    op.create_table(
        "prompt_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_prompt_version_name_version"),
    )
    op.create_table(
        "evaluation_report",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rubric_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("logic_score", sa.Integer(), nullable=True),
        sa.Column("speech_score", sa.Integer(), nullable=True),
        sa.Column("adaptability_score", sa.Integer(), nullable=True),
        sa.Column("final_score", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'INVALID', 'FAILED')",
            name="ck_evaluation_report_status",
        ),
        sa.ForeignKeyConstraint(["rubric_id"], ["question_rubric.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["training_session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_evaluation_report_session_id"),
    )
    op.create_table(
        "evaluation_issue",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transcript_segment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("missing_information", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correction_rule", sa.Text(), nullable=False),
        sa.Column("verification_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('logic', 'speech', 'adaptability')", name="ck_issue_category"
        ),
        sa.CheckConstraint("confidence IN ('low', 'medium', 'high')", name="ck_issue_confidence"),
        sa.ForeignKeyConstraint(["attempt_id"], ["voice_attempt.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["evaluation_report.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["transcript_segment_id"],
            ["transcript_segment.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "report_id",
            "attempt_id",
            "code",
            "quote",
            "start_ms",
            "end_ms",
            name="uq_evaluation_issue_evidence",
        ),
    )
    op.create_table(
        "model_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("prompt_name", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("input_characters", sa.Integer(), nullable=True),
        sa.Column("output_characters", sa.Integer(), nullable=True),
        sa.Column("structured_ok", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("input_summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["ai_job.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["report_id"], ["evaluation_report.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_run_report_id", "model_run", ["report_id"])
    op.create_index("ix_model_run_job_id", "model_run", ["job_id"])
    op.create_index("ix_evaluation_issue_report_id", "evaluation_issue", ["report_id"])
    op.create_index("ix_evaluation_issue_attempt_id", "evaluation_issue", ["attempt_id"])
    op.create_index("ix_question_rubric_session_id", "question_rubric", ["training_session_id"])


def downgrade() -> None:
    op.drop_index("ix_question_rubric_session_id", table_name="question_rubric")
    op.drop_index("ix_evaluation_issue_attempt_id", table_name="evaluation_issue")
    op.drop_index("ix_evaluation_issue_report_id", table_name="evaluation_issue")
    op.drop_index("ix_model_run_job_id", table_name="model_run")
    op.drop_index("ix_model_run_report_id", table_name="model_run")
    op.drop_table("model_run")
    op.drop_table("evaluation_issue")
    op.drop_table("evaluation_report")
    op.drop_table("prompt_version")
    op.drop_table("question_rubric")
