from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Question,
    QuestionClaimMap,
    QuestionFingerprint,
    QuestionRubric,
    QuestionSource,
    SourceBundle,
    SourceClaim,
)


async def seed_ready_question(
    session: AsyncSession,
    *,
    user_id: UUID,
    question_id: UUID | None = None,
    prompt: str = "请基于材料说明你的判断、证据缺口和下一步。",
) -> Question:
    if question_id is not None:
        existing = await session.get(Question, question_id)
        if existing is not None:
            return existing

    effective_question_id = question_id or uuid4()
    suffix = effective_question_id.hex[:12]
    bundle = SourceBundle(
        user_id=user_id,
        status="READY",
        target_defects=["ALIGN-01"],
        search_queries=["official report decision evidence"],
        source_count=1,
        highest_source_level="A",
        credential=f"SRC-TEST-{suffix}",
        prompt_versions_json={
            "search_direction": "test",
            "claim_extraction": "test",
            "claim_verification": "test",
            "question_generation": "test",
            "rubric_generation": "test",
        },
    )
    session.add(bundle)
    await session.flush()

    source = QuestionSource(
        source_bundle_id=bundle.id,
        title="Test official source",
        publisher="Example official report",
        url=f"https://example.com/source/{suffix}",
        level="A",
        content_type="text/html",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        snapshot_hash=hashlib.sha256(suffix.encode("utf-8")).hexdigest(),
        extracted_characters=120,
        fetch_status="SUCCEEDED",
    )
    session.add(source)
    await session.flush()

    claim = SourceClaim(
        source_id=source.id,
        claim_text="材料显示团队没有更新成功标准。",
        locator="paragraph 1",
        excerpt="团队没有更新成功标准",
        support_status="VERIFIED",
        verifier_reason="test verified claim",
    )
    session.add(claim)
    await session.flush()

    question = Question(
        id=effective_question_id,
        user_id=user_id,
        source_bundle_id=bundle.id,
        prompt=prompt,
        type="decision",
        target_defects=["ALIGN-01"],
        status="READY",
        exposed_count=0,
        unsupported_claim_count=0,
        prompt_version="test",
        expected_reasoning_json=["区分事实、假设和未知"],
        prohibited_inferences_json=["不得补充来源未支持的因果"],
        hypothetical_assumptions_json=[],
        ready_at=datetime.now(UTC),
    )
    session.add(question)
    await session.flush()

    session.add(
        QuestionFingerprint(
            question_id=question.id,
            normalized_hash=hashlib.sha256(f"question:{suffix}".encode()).hexdigest(),
            structural_json={"template_family": "test-p08", "suffix": suffix},
            template_family="test-p08",
            source_event_id=f"event-{suffix}",
        )
    )
    session.add(
        QuestionClaimMap(
            question_id=question.id,
            claim_id=claim.id,
            usage_type="fact",
            sentence_index=0,
            sentence_text="材料显示团队没有更新成功标准。",
        )
    )
    session.add(
        QuestionRubric(
            training_session_id=None,
            question_id=question.id,
            version="test-rubric",
            dimensions_json={"logic": 60, "evidence": 40},
            expected_elements_json=["结论", "证据", "下一步"],
            fatal_omissions_json=["无视来源事实"],
            content_hash=hashlib.sha256(f"rubric:{suffix}".encode()).hexdigest(),
        )
    )
    await session.flush()
    return question
