"""add defect memory and profile tables

Revision ID: 0006_defect_memory
Revises: 0005_evaluation
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006_defect_memory"
down_revision = "0005_evaluation"
branch_labels = None
depends_on = None


DEFECT_DEFINITIONS = [
    ("ALIGN-01", "答非所问", "未回应题目或对方真正要求的决策。"),
    ("LEVEL-01", "过早进入实现层", "目标或决策未明确就讨论代码、流程或任务拆分。"),
    ("LEVEL-02", "局部问题替代整体问题", "用自己熟悉的小问题替代系统问题。"),
    ("GOAL-01", "把手段当目标", "方案、工具或动作被当作最终价值。"),
    ("GOAL-02", "缺少成功标准", "无法说明做到什么程度才算有效。"),
    ("STRUCT-01", "没有明确结论", "大量描述后仍无法识别主张。"),
    ("STRUCT-02", "过程代替结论", "只汇报做过什么，不说明当前判断和结果。"),
    ("STRUCT-03", "层级混乱", "目标、理由、风险和行动交叉堆叠。"),
    ("STRUCT-04", "框架正确但内容空泛", "只说通用模板，未结合本题事实。"),
    ("INFO-01", "事实与假设混淆", "把推测当作已确认事实。"),
    ("INFO-02", "信息不足仍强行下结论", "不说明未知、边界和暂定性。"),
    ("EVID-01", "证据不支持结论", "依据与结论之间缺少支撑。"),
    ("CAUSE-01", "因果链断裂", "从现象直接跳到结论。"),
    ("CAUSE-02", "单因解释复杂问题", "忽略替代原因和相互作用。"),
    ("DEC-01", "没有备选方案", "决策题只给一个方案。"),
    ("DEC-02", "没有取舍标准", "没有说明为什么选、放弃什么。"),
    ("RISK-01", "缺少反例与失败预案", "未考虑什么会推翻判断。"),
    ("SYS-01", "忽略利益相关方", "遗漏客户、团队、公司或合作方。"),
    ("SYS-02", "局部最优代替整体最优", "只优化自己或本部门。"),
    ("SYS-03", "忽略长期或二阶影响", "只看直接、短期结果。"),
    ("MGMT-01", "把人的问题当流程问题", "未判断能力、意愿、冲突和权责。"),
    ("MGMT-02", "责任与决策权不清", "没有明确谁负责、谁拍板。"),
    ("MGMT-03", "只安排任务不处理动机", "忽略激励、认同和行为边界。"),
    ("MGMT-04", "过度依赖个人执行", "倾向自己完成，而非通过团队交付。"),
    ("COMM-01", "重点不清", "信息多但听众无法识别主线。"),
    ("COMM-02", "对象不匹配", "没有根据领导、同事、下属或客户调整表达。"),
    ("EXEC-01", "行动抽象", "“研究、看看、梳理”没有可见产物。"),
    ("EXEC-02", "缺少责任或期限", "无法形成执行闭环。"),
    ("EXEC-03", "缺少验证标准", "没有说明如何判断行动是否有效。"),
    ("SPEECH-01", "结论出现过晚", "前段铺垫过长。"),
    ("SPEECH-02", "重复与口头禅过多", "影响可听性和信息密度。"),
    ("SPEECH-03", "长句混合多个层级", "一句话承载结论、背景、风险和行动。"),
    ("ADAPT-01", "未回应追问核心", "被追问后继续重复原答案。"),
    ("ADAPT-02", "新信息下拒绝更新", "证据变化仍机械固守。"),
]


def upgrade() -> None:
    op.create_table(
        "defect_definition",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("detection_rule", sa.Text(), nullable=False),
        sa.Column("score_cap", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("code"),
    )
    _seed_defect_definitions()
    op.create_table(
        "appeal",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("defect_code", sa.String(length=64), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
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
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "type IN ('evaluation', 'defect_classification')",
            name="ck_appeal_type",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'REVIEWED_ACCEPTED', 'REVIEWED_REJECTED')",
            name="ck_appeal_status",
        ),
        sa.ForeignKeyConstraint(["defect_code"], ["defect_definition.code"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["issue_id"], ["evaluation_issue.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["training_session.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "defect_occurrence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("defect_code", sa.String(length=64), nullable=False),
        sa.Column("source_issue_code", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("scenario_key", sa.String(length=128), nullable=False),
        sa.Column("attempt_stage", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("previous_status", sa.String(length=16), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("suspending_appeal_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            "status IN ('PENDING', 'ACTIVE', 'SUSPENDED', 'EXCLUDED')",
            name="ck_defect_occurrence_status",
        ),
        sa.CheckConstraint(
            "previous_status IS NULL OR previous_status IN ('PENDING', 'ACTIVE')",
            name="ck_defect_occurrence_previous_status",
        ),
        sa.CheckConstraint(
            "confidence IN ('low', 'medium', 'high')",
            name="ck_defect_occurrence_confidence",
        ),
        sa.ForeignKeyConstraint(["defect_code"], ["defect_definition.code"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["issue_id"], ["evaluation_issue.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["training_session.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["suspending_appeal_id"],
            ["appeal.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "issue_id",
            "defect_code",
            name="uq_defect_occurrence_session_issue_code",
        ),
    )
    op.create_table(
        "defect_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurrence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transcript_segment_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(["attempt_id"], ["voice_attempt.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issue_id"], ["evaluation_issue.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["defect_occurrence.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_segment_id"],
            ["transcript_segment.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("occurrence_id", name="uq_defect_evidence_occurrence_id"),
    )
    op.create_table(
        "defect_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("defect_code", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("frequency", sa.Integer(), nullable=False),
        sa.Column("recurrence", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("active_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("suspended_occurrence_count", sa.Integer(), nullable=False),
        sa.Column("scenario_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
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
            "state IN ('observed', 'confirmed', 'high-priority', "
            "'improving', 'stable-improved')",
            name="ck_defect_profile_state",
        ),
        sa.ForeignKeyConstraint(["defect_code"], ["defect_definition.code"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "defect_code", name="uq_defect_profile_user_code"),
    )
    op.create_index("ix_appeal_user_session", "appeal", ["user_id", "session_id"])
    op.create_index(
        "ix_defect_occurrence_user_code",
        "defect_occurrence",
        ["user_id", "defect_code"],
    )
    op.create_index("ix_defect_occurrence_issue_id", "defect_occurrence", ["issue_id"])
    op.create_index("ix_defect_evidence_issue_id", "defect_evidence", ["issue_id"])
    op.create_index(
        "ix_defect_profile_user_priority",
        "defect_profile",
        ["user_id", "priority"],
    )


def downgrade() -> None:
    op.drop_index("ix_defect_profile_user_priority", table_name="defect_profile")
    op.drop_index("ix_defect_evidence_issue_id", table_name="defect_evidence")
    op.drop_index("ix_defect_occurrence_issue_id", table_name="defect_occurrence")
    op.drop_index("ix_defect_occurrence_user_code", table_name="defect_occurrence")
    op.drop_index("ix_appeal_user_session", table_name="appeal")
    op.drop_table("defect_profile")
    op.drop_table("defect_evidence")
    op.drop_table("defect_occurrence")
    op.drop_table("appeal")
    op.drop_table("defect_definition")


def _seed_defect_definitions() -> None:
    table = sa.table(
        "defect_definition",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("detection_rule", sa.Text),
        sa.column("score_cap", sa.Integer),
    )
    op.bulk_insert(
        table,
        [
            {
                "code": code,
                "name": name,
                "description": description,
                "detection_rule": description,
                "score_cap": None,
            }
            for code, name, description in DEFECT_DEFINITIONS
        ],
    )
