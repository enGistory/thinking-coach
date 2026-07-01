"""add release reporting and privacy deletion tables

Revision ID: 0010_release_privacy
Revises: 0009_random_strike
Create Date: 2026-06-25
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010_release_privacy"
down_revision = "0009_random_strike"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_appeal_type", "appeal", type_="check")
    op.add_column(
        "appeal",
        sa.Column(
            "target_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column("appeal", "target_json", server_default=None)
    op.create_check_constraint(
        "ck_appeal_type",
        "appeal",
        "type IN ('transcript', 'source', 'evaluation', 'defect_classification')",
    )

    op.create_table(
        "weekly_report",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
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
        sa.UniqueConstraint("user_id", "week_start", name="uq_weekly_report_user_week"),
    )
    op.create_index(
        "ix_weekly_report_user_week",
        "weekly_report",
        ["user_id", "week_start"],
    )

    op.create_table(
        "privacy_deletion_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id_snapshot", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id_hash", sa.String(length=64), nullable=False),
        sa.Column("proof_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "counts_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_privacy_deletion_request_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.alter_column("privacy_deletion_request", "counts_json", server_default=None)
    op.create_index(
        "ix_privacy_deletion_request_user",
        "privacy_deletion_request",
        ["user_id_snapshot"],
    )
    op.create_index(
        "ix_privacy_deletion_request_status",
        "privacy_deletion_request",
        ["status"],
    )

    op.create_table(
        "privacy_audit_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id_snapshot", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "counts_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.alter_column("privacy_audit_event", "counts_json", server_default=None)
    op.create_index(
        "ix_privacy_audit_event_user",
        "privacy_audit_event",
        ["user_id_snapshot"],
    )
    op.create_index(
        "ix_privacy_audit_event_request",
        "privacy_audit_event",
        ["request_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_privacy_audit_event_request", table_name="privacy_audit_event")
    op.drop_index("ix_privacy_audit_event_user", table_name="privacy_audit_event")
    op.drop_table("privacy_audit_event")

    op.drop_index("ix_privacy_deletion_request_status", table_name="privacy_deletion_request")
    op.drop_index("ix_privacy_deletion_request_user", table_name="privacy_deletion_request")
    op.drop_table("privacy_deletion_request")

    op.drop_index("ix_weekly_report_user_week", table_name="weekly_report")
    op.drop_table("weekly_report")

    op.drop_constraint("ck_appeal_type", "appeal", type_="check")
    op.drop_column("appeal", "target_json")
    op.create_check_constraint(
        "ck_appeal_type",
        "appeal",
        "type IN ('evaluation', 'defect_classification')",
    )
