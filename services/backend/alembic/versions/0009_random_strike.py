"""add random strike scheduling and push subscriptions

Revision ID: 0009_random_strike
Revises: 0008_never_repeat
Create Date: 2026-06-24
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009_random_strike"
down_revision = "0008_never_repeat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscription",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint", name="uq_push_subscription_endpoint"),
    )
    op.create_index(
        "ix_push_subscription_user_active",
        "push_subscription",
        ["user_id", "active"],
    )

    op.add_column(
        "training_session",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "training_session",
        sa.Column("notification_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "training_session",
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "training_session",
        sa.Column(
            "delivery_decision_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column("training_session", "delivery_decision_json", server_default=None)
    op.add_column(
        "training_session",
        sa.Column(
            "deferred_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.alter_column("training_session", "deferred_count", server_default=None)
    op.add_column(
        "training_session",
        sa.Column("push_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "training_session",
        sa.Column("push_error_code", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_training_session_user_stage",
        "training_session",
        ["user_id", "stage"],
    )
    op.create_index(
        "uq_training_session_user_active",
        "training_session",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(
            "stage NOT IN ("
            "'COMPLETED', 'EXPIRED', 'ABANDONED', 'INVALID', 'FAILED_RETRYABLE'"
            ")"
        ),
    )
    op.create_index(
        "ix_training_session_stage_scheduled",
        "training_session",
        ["stage", "scheduled_at"],
    )
    op.create_index(
        "ix_training_session_notification_expires",
        "training_session",
        ["stage", "notification_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_training_session_notification_expires",
        table_name="training_session",
    )
    op.drop_index("ix_training_session_stage_scheduled", table_name="training_session")
    op.drop_index("uq_training_session_user_active", table_name="training_session")
    op.drop_index("ix_training_session_user_stage", table_name="training_session")
    op.drop_column("training_session", "push_error_code")
    op.drop_column("training_session", "push_status")
    op.drop_column("training_session", "deferred_count")
    op.drop_column("training_session", "delivery_decision_json")
    op.drop_column("training_session", "accepted_at")
    op.drop_column("training_session", "notification_expires_at")
    op.drop_column("training_session", "notified_at")
    op.drop_index("ix_push_subscription_user_active", table_name="push_subscription")
    op.drop_table("push_subscription")
