from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (
        CheckConstraint("role IN ('USER', 'ADMIN')", name="ck_app_user_role"),
        CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="ck_app_user_status"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    nickname: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="USER")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Invitation(Base):
    __tablename__ = "invitation"
    __table_args__ = (CheckConstraint("role IN ('USER', 'ADMIN')", name="ck_invitation_role"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="USER")
    created_by_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="RESTRICT"),
        nullable=False,
    )
    used_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_token"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class UserTrainingPolicy(Base):
    __tablename__ = "user_training_policy"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    windows: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    quiet_hours: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    daily_max: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PushSubscription(Base):
    __tablename__ = "push_subscription"
    __table_args__ = (
        UniqueConstraint("endpoint", name="uq_push_subscription_endpoint"),
        Index("ix_push_subscription_user_active", "user_id", "active"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SourceBundle(Base):
    __tablename__ = "source_bundle"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'READY', 'INVALID')",
            name="ck_source_bundle_status",
        ),
        Index("ix_source_bundle_user_status", "user_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    target_defects: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    search_queries: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    highest_source_level: Mapped[str | None] = mapped_column(String(1), nullable=True)
    credential: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    prompt_versions_json: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class QuestionSource(Base):
    __tablename__ = "question_source"
    __table_args__ = (
        CheckConstraint("level IN ('S', 'A', 'B', 'C')", name="ck_question_source_level"),
        UniqueConstraint("source_bundle_id", "url", name="uq_question_source_bundle_url"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_bundle_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("source_bundle.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str] = mapped_column(String(256), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(String(1), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extracted_characters: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetch_status: Mapped[str] = mapped_column(String(32), nullable=False, default="SUCCEEDED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class SourceClaim(Base):
    __tablename__ = "source_claim"
    __table_args__ = (
        CheckConstraint(
            "support_status IN ('VERIFIED', 'CONFLICTED', 'UNSUPPORTED')",
            name="ck_source_claim_support_status",
        ),
        Index("ix_source_claim_source_status", "source_id", "support_status"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("question_source.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[str] = mapped_column(String(256), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    support_status: Mapped[str] = mapped_column(String(16), nullable=False)
    verifier_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Question(Base):
    __tablename__ = "question"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'VERIFIED', 'DEDUPED', 'READY', 'EXPOSED', 'RETIRED', 'INVALID')",
            name="ck_question_status",
        ),
        Index("ix_question_user_status", "user_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_bundle_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("source_bundle.id", ondelete="CASCADE"),
        nullable=False,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_defects: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    exposed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unsupported_claim_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_reasoning_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    prohibited_inferences_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    hypothetical_assumptions_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class QuestionClaimMap(Base):
    __tablename__ = "question_claim_map"
    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "claim_id",
            "sentence_index",
            "usage_type",
            name="uq_question_claim_map_fact",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    question_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("question.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("source_claim.id", ondelete="RESTRICT"),
        nullable=False,
    )
    usage_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sentence_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sentence_text: Mapped[str] = mapped_column(Text, nullable=False, default="")


class QuestionFingerprint(Base):
    __tablename__ = "question_fingerprint"
    __table_args__ = (UniqueConstraint("question_id", name="uq_question_fingerprint_question_id"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    question_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("question.id", ondelete="CASCADE"),
        nullable=False,
    )
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    structural_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    template_family: Mapped[str] = mapped_column(String(128), nullable=False, default="p08")
    source_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    summary_embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    decision_embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    answer_skeleton_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dedupe_decision_json: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class QuestionDedupeCheck(Base):
    __tablename__ = "question_dedupe_check"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('PASS', 'REJECT')",
            name="ck_question_dedupe_check_decision",
        ),
        Index("ix_question_dedupe_check_user_created", "user_id", "created_at"),
        Index("ix_question_dedupe_check_question_id", "question_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_bundle_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("source_bundle.id", ondelete="CASCADE"),
        nullable=True,
    )
    question_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("question.id", ondelete="SET NULL"),
        nullable=True,
    )
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    template_family: Mapped[str] = mapped_column(String(128), nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    rejection_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    max_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    structure_change_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    matched_question_ids_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    input_summary_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    decision_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class QuestionTemplateDenylist(Base):
    __tablename__ = "question_template_denylist"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "template_family",
            name="uq_question_template_deny_user_family",
        ),
        Index("ix_question_template_deny_user", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_family: Mapped[str] = mapped_column(String(128), nullable=False)
    trigger_question_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("question.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class QuestionDuplicateComplaint(Base):
    __tablename__ = "question_duplicate_complaint"
    __table_args__ = (
        CheckConstraint(
            "duplicate_type IN ("
            "'text', 'semantic', 'parameter', 'role', 'structure', "
            "'answer_skeleton', 'same_event', 'other'"
            ")",
            name="ck_question_duplicate_complaint_type",
        ),
        CheckConstraint(
            "status IN ('ACCEPTED')",
            name="ck_question_duplicate_complaint_status",
        ),
        UniqueConstraint("user_id", "session_id", name="uq_question_duplicate_complaint_session"),
        Index("ix_question_duplicate_complaint_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("training_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("question.id", ondelete="CASCADE"),
        nullable=False,
    )
    similar_question_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("question.id", ondelete="SET NULL"),
        nullable=True,
    )
    duplicate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    template_family: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACCEPTED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class TrainingSession(Base):
    __tablename__ = "training_session"
    __table_args__ = (
        CheckConstraint(
            "stage IN ("
            "'SCHEDULED', 'NOTIFIED', 'ACCEPTED', 'QUESTION_EXPOSED', "
            "'WAIT_FIRST_AUDIO', 'PROCESS_FIRST', 'WAIT_FOLLOWUP_AUDIO', "
            "'PROCESS_FOLLOWUP', 'WAIT_FINAL_AUDIO', 'EVALUATING', 'COMPLETED', "
            "'EXPIRED', 'ABANDONED', 'INVALID', 'FAILED_RETRYABLE'"
            ")",
            name="ck_training_session_stage",
        ),
        Index("ix_training_session_user_stage", "user_id", "stage"),
        Index(
            "uq_training_session_user_active",
            "user_id",
            unique=True,
            postgresql_where=text(
                "stage NOT IN ('COMPLETED', 'EXPIRED', 'ABANDONED', 'INVALID', 'FAILED_RETRYABLE')"
            ),
        ),
        Index("ix_training_session_stage_scheduled", "stage", "scheduled_at"),
        Index("ix_training_session_notification_expires", "stage", "notification_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("question.id", ondelete="SET NULL"),
        nullable=True,
    )
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="WAIT_FIRST_AUDIO")
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_decision_json: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    deferred_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    push_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    push_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class VoiceAttempt(Base):
    __tablename__ = "voice_attempt"
    __table_args__ = (
        CheckConstraint("stage IN ('FIRST', 'FOLLOWUP', 'FINAL')", name="ck_voice_attempt_stage"),
        CheckConstraint(
            "upload_status IN ('PENDING', 'UPLOADED', 'FAILED')",
            name="ck_voice_attempt_upload_status",
        ),
        UniqueConstraint(
            "session_id",
            "stage",
            "round",
            name="uq_voice_attempt_session_stage_round",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("training_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    upload_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    retention_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AttemptTranscript(Base):
    __tablename__ = "attempt_transcript"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_attempt_transcript_status",
        ),
        UniqueConstraint("attempt_id", name="uq_attempt_transcript_attempt_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("voice_attempt.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    corrected_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metrics_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TranscriptSegment(Base):
    __tablename__ = "transcript_segment"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "segment_index",
            name="uq_transcript_segment_attempt_index",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("voice_attempt.id", ondelete="CASCADE"),
        nullable=False,
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_text: Mapped[str] = mapped_column(Text, nullable=False)
    words_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="asr")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TranscriptCorrection(Base):
    __tablename__ = "transcript_correction"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("voice_attempt.id", ondelete="CASCADE"),
        nullable=False,
    )
    segment_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("transcript_segment.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    previous_corrected_text: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_text: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class QuestionRubric(Base):
    __tablename__ = "question_rubric"
    __table_args__ = (
        UniqueConstraint(
            "training_session_id",
            "version",
            name="uq_question_rubric_session_version",
        ),
        UniqueConstraint(
            "question_id",
            "version",
            name="uq_question_rubric_question_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    training_session_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("training_session.id", ondelete="CASCADE"),
        nullable=True,
    )
    question_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("question.id", ondelete="CASCADE"),
        nullable=True,
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    dimensions_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    expected_elements_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    fatal_omissions_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PromptVersion(Base):
    __tablename__ = "prompt_version"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_prompt_version_name_version"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class EvaluationReport(Base):
    __tablename__ = "evaluation_report"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'INVALID', 'FAILED')",
            name="ck_evaluation_report_status",
        ),
        UniqueConstraint("session_id", name="uq_evaluation_report_session_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("training_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    rubric_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("question_rubric.id", ondelete="SET NULL"),
        nullable=True,
    )
    logic_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speech_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adaptability_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    details_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvaluationIssue(Base):
    __tablename__ = "evaluation_issue"
    __table_args__ = (
        CheckConstraint(
            "category IN ('logic', 'speech', 'adaptability')",
            name="ck_issue_category",
        ),
        CheckConstraint("confidence IN ('low', 'medium', 'high')", name="ck_issue_confidence"),
        UniqueConstraint(
            "report_id",
            "attempt_id",
            "code",
            "quote",
            "start_ms",
            "end_ms",
            name="uq_evaluation_issue_evidence",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    report_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("evaluation_report.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("voice_attempt.id", ondelete="CASCADE"),
        nullable=False,
    )
    transcript_segment_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("transcript_segment.id", ondelete="SET NULL"),
        nullable=True,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    missing_information: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    correction_rule: Mapped[str] = mapped_column(Text, nullable=False)
    verification_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class DefectDefinition(Base):
    __tablename__ = "defect_definition"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    detection_rule: Mapped[str] = mapped_column(Text, nullable=False)
    score_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Appeal(Base):
    __tablename__ = "appeal"
    __table_args__ = (
        CheckConstraint(
            "type IN ('evaluation', 'defect_classification')",
            name="ck_appeal_type",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'REVIEWED_ACCEPTED', 'REVIEWED_REJECTED')",
            name="ck_appeal_status",
        ),
        Index("ix_appeal_user_session", "user_id", "session_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("training_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    issue_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("evaluation_issue.id", ondelete="SET NULL"),
        nullable=True,
    )
    defect_code: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("defect_definition.code", ondelete="SET NULL"),
        nullable=True,
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DefectOccurrence(Base):
    __tablename__ = "defect_occurrence"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'SUSPENDED', 'EXCLUDED')",
            name="ck_defect_occurrence_status",
        ),
        CheckConstraint(
            "previous_status IS NULL OR previous_status IN ('PENDING', 'ACTIVE')",
            name="ck_defect_occurrence_previous_status",
        ),
        CheckConstraint(
            "confidence IN ('low', 'medium', 'high')",
            name="ck_defect_occurrence_confidence",
        ),
        UniqueConstraint(
            "session_id",
            "issue_id",
            "defect_code",
            name="uq_defect_occurrence_session_issue_code",
        ),
        Index("ix_defect_occurrence_user_code", "user_id", "defect_code"),
        Index("ix_defect_occurrence_issue_id", "issue_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("training_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    issue_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("evaluation_issue.id", ondelete="CASCADE"),
        nullable=False,
    )
    defect_code: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("defect_definition.code", ondelete="RESTRICT"),
        nullable=False,
    )
    source_issue_code: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    scenario_key: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_stage: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suspending_appeal_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("appeal.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DefectEvidence(Base):
    __tablename__ = "defect_evidence"
    __table_args__ = (
        UniqueConstraint("occurrence_id", name="uq_defect_evidence_occurrence_id"),
        Index("ix_defect_evidence_issue_id", "issue_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    occurrence_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("defect_occurrence.id", ondelete="CASCADE"),
        nullable=False,
    )
    issue_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("evaluation_issue.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("voice_attempt.id", ondelete="CASCADE"),
        nullable=False,
    )
    transcript_segment_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("transcript_segment.id", ondelete="SET NULL"),
        nullable=True,
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    missing_information: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    correction_rule: Mapped[str] = mapped_column(Text, nullable=False)
    verification_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class DefectProfile(Base):
    __tablename__ = "defect_profile"
    __table_args__ = (
        CheckConstraint(
            "state IN ('observed', 'confirmed', 'high-priority', 'improving', 'stable-improved')",
            name="ck_defect_profile_state",
        ),
        UniqueConstraint("user_id", "defect_code", name="uq_defect_profile_user_code"),
        Index("ix_defect_profile_user_priority", "user_id", "priority"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    defect_code: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("defect_definition.code", ondelete="RESTRICT"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frequency: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recurrence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suspended_occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scenario_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AIJob(Base):
    __tablename__ = "ai_job"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'FAILED', 'SUCCEEDED')",
            name="ck_ai_job_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ModelRun(Base):
    __tablename__ = "model_run"
    __table_args__ = (
        Index("ix_model_run_report_id", "report_id"),
        Index("ix_model_run_job_id", "job_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("ai_job.id", ondelete="SET NULL"),
        nullable=True,
    )
    report_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("evaluation_report.id", ondelete="CASCADE"),
        nullable=True,
    )
    prompt_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_characters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_characters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    structured_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_summary_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    output_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
