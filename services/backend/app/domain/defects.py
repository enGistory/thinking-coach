from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

DefectState = Literal["observed", "confirmed", "high-priority", "improving", "stable-improved"]
OccurrenceStatus = Literal["PENDING", "ACTIVE", "SUSPENDED", "EXCLUDED"]
ConfidenceLevel = Literal["low", "medium", "high"]

IMPROVEMENT_STATES = {"improving", "stable-improved"}
CONFIRMED_STATES = {"confirmed", "high-priority", "improving", "stable-improved"}


@dataclass(frozen=True)
class DefectDefinitionSpec:
    code: str
    name: str
    description: str
    detection_rule: str
    score_cap: int | None = None


@dataclass(frozen=True)
class ProfileOccurrence:
    severity: int
    confidence: ConfidenceLevel
    scenario_key: str
    attempt_stage: str
    status: OccurrenceStatus
    created_at: datetime


@dataclass(frozen=True)
class ProfileStats:
    state: DefectState
    severity: int
    frequency: int
    recurrence: int
    priority: int
    confidence: int
    active_occurrence_count: int
    suspended_occurrence_count: int
    scenario_count: int
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    confirmed: bool


SPEC_DEFECT_DEFINITIONS = tuple(
    DefectDefinitionSpec(
        code=code,
        name=name,
        description=description,
        detection_rule=description,
    )
    for code, name, description in (
        ("ALIGN-01", "答非所问", "未回应题目或对方真正要求的决策。"),
        ("LEVEL-01", "过早进入实现层", "目标或决策未明确就讨论代码、流程或任务拆分。"),
        ("LEVEL-02", "局部问题替代整体问题", "用自己熟悉的小问题替代系统问题。"),
        ("GOAL-01", "把手段当目标", "方案、工具或动作被当作最终价值。"),
        ("GOAL-02", "缺少成功标准", "无法说明做到什么程度才算有效。"),
        ("STRUCT-01", "没有明确结论", "大量描述后仍无法识别主张。"),
        ("STRUCT-02", "过程代替结论", "只汇报做过什么, 不说明当前判断和结果。"),
        ("STRUCT-03", "层级混乱", "目标、理由、风险和行动交叉堆叠。"),
        ("STRUCT-04", "框架正确但内容空泛", "只说通用模板, 未结合本题事实。"),
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
        ("MGMT-04", "过度依赖个人执行", "倾向自己完成, 而非通过团队交付。"),
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
    )
)

SPEC_DEFECT_CODES = {definition.code for definition in SPEC_DEFECT_DEFINITIONS}

DEFECT_CODE_ALIASES = {
    "NO_DECISION": "STRUCT-01",
    "ASSUMPTION_AS_FACT": "INFO-01",
    "SINGLE_OPTION": "DEC-01",
    "GENERIC_FRAMEWORK": "STRUCT-04",
}


def normalize_defect_code(code: str) -> str | None:
    normalized = code.strip().upper()
    normalized = DEFECT_CODE_ALIASES.get(normalized, normalized)
    if normalized in SPEC_DEFECT_CODES:
        return normalized
    return None


def occurrence_status_for_confidence(confidence: ConfidenceLevel) -> OccurrenceStatus:
    return "PENDING" if confidence == "low" else "ACTIVE"


def calculate_profile_stats(
    occurrences: list[ProfileOccurrence],
    *,
    previous_state: str | None = None,
    previous_recurrence: int = 0,
) -> ProfileStats:
    active = [item for item in occurrences if item.status == "ACTIVE"]
    suspended_count = sum(1 for item in occurrences if item.status == "SUSPENDED")
    if not active:
        state = _empty_state(previous_state)
        recurrence = _clamp(previous_recurrence, minimum=0, maximum=1) if suspended_count else 0
        return ProfileStats(
            state=state,
            severity=0,
            frequency=0,
            recurrence=recurrence,
            priority=0,
            confidence=0,
            active_occurrence_count=0,
            suspended_occurrence_count=suspended_count,
            scenario_count=0,
            first_seen_at=None,
            last_seen_at=None,
            confirmed=False,
        )

    severity = max(_clamp(item.severity, minimum=1, maximum=5) for item in active)
    confidence = round(sum(_confidence_value(item.confidence) for item in active) / len(active))
    scenario_count = len({item.scenario_key for item in active})
    first_stage_count = sum(1 for item in active if item.attempt_stage == "FIRST")
    confirmed = len(active) >= 3 and scenario_count >= 2 and first_stage_count >= 2
    recurrence = _recurrence_value(previous_state, previous_recurrence)
    state = _state_for_active_occurrences(
        confirmed=confirmed,
        severity=severity,
        frequency=len(active),
        recurrence=recurrence,
    )
    priority = _priority(
        severity=severity,
        frequency=len(active),
        recurrence=recurrence,
        scenario_count=scenario_count,
        confidence=confidence,
    )
    created_times = [item.created_at for item in active]
    return ProfileStats(
        state=state,
        severity=severity,
        frequency=len(active),
        recurrence=recurrence,
        priority=priority,
        confidence=confidence,
        active_occurrence_count=len(active),
        suspended_occurrence_count=suspended_count,
        scenario_count=scenario_count,
        first_seen_at=min(created_times),
        last_seen_at=max(created_times),
        confirmed=state in CONFIRMED_STATES,
    )


def _empty_state(previous_state: str | None) -> DefectState:
    if previous_state == "stable-improved":
        return "stable-improved"
    if previous_state == "improving":
        return "improving"
    return "observed"


def _recurrence_value(previous_state: str | None, previous_recurrence: int) -> int:
    if previous_state in IMPROVEMENT_STATES:
        return 1
    return _clamp(previous_recurrence, minimum=0, maximum=1)


def _state_for_active_occurrences(
    *,
    confirmed: bool,
    severity: int,
    frequency: int,
    recurrence: int,
) -> DefectState:
    if recurrence:
        return "high-priority"
    if not confirmed:
        return "observed"
    if severity >= 4 or frequency >= 5:
        return "high-priority"
    return "confirmed"


def _priority(
    *,
    severity: int,
    frequency: int,
    recurrence: int,
    scenario_count: int,
    confidence: int,
) -> int:
    severity_norm = severity / 5
    frequency_norm = min(frequency / 5, 1.0)
    cross_domain_norm = min(scenario_count / 2, 1.0)
    uncertainty_norm = 1 - confidence / 100
    value = 100 * (
        0.28 * severity_norm
        + 0.20 * frequency_norm
        + 0.18 * recurrence
        + 0.14 * cross_domain_norm
        + 0.10 * 0.5
        + 0.10 * uncertainty_norm
    )
    return _clamp(round(value), minimum=0, maximum=100)


def _confidence_value(confidence: ConfidenceLevel) -> int:
    if confidence == "high":
        return 100
    if confidence == "medium":
        return 65
    return 30


def _clamp(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))
