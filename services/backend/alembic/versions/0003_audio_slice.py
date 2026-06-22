"""create training sessions and voice attempts

Revision ID: 0003_audio_slice
Revises: 0002_database_auth
Create Date: 2026-06-21
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_audio_slice"
down_revision = "0002_database_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("exposed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "stage IN ("
            "'SCHEDULED', 'NOTIFIED', 'ACCEPTED', 'QUESTION_EXPOSED', "
            "'WAIT_FIRST_AUDIO', 'PROCESS_FIRST', 'WAIT_FOLLOWUP_AUDIO', "
            "'PROCESS_FOLLOWUP', 'WAIT_FINAL_AUDIO', 'EVALUATING', 'COMPLETED', "
            "'EXPIRED', 'ABANDONED', 'INVALID', 'FAILED_RETRYABLE'"
            ")",
            name="ck_training_session_stage",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", name="uq_training_session_thread_id"),
    )
    op.create_table(
        "voice_attempt",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("audio_path", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("upload_status", sa.String(length=16), nullable=False),
        sa.Column("retention_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("stage IN ('FIRST', 'FOLLOWUP', 'FINAL')", name="ck_voice_attempt_stage"),
        sa.CheckConstraint(
            "upload_status IN ('PENDING', 'UPLOADED', 'FAILED')",
            name="ck_voice_attempt_upload_status",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["training_session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "stage",
            "round",
            name="uq_voice_attempt_session_stage_round",
        ),
    )
    op.create_index("ix_training_session_user_id", "training_session", ["user_id"])
    op.create_index("ix_voice_attempt_session_id", "voice_attempt", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_voice_attempt_session_id", table_name="voice_attempt")
    op.drop_index("ix_training_session_user_id", table_name="training_session")
    op.drop_table("voice_attempt")
    op.drop_table("training_session")
