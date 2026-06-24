from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from app.domain.source_question import (
    ClaimGateInput,
    classify_source_level,
    normalized_question_hash,
    question_ready,
    usable_claim_ids,
)
from app.services.source_questions import _bundle_credential


def test_classifies_official_and_low_quality_sources() -> None:
    assert (
        classify_source_level(
            title="年度统计报告",
            publisher="国家统计局",
            url="https://www.stats.gov.cn/report",
        )
        == "S"
    )
    assert (
        classify_source_level(
            title="项目复盘",
            publisher="Example Research University",
            url="https://example.edu/research/report",
        )
        == "A"
    )
    assert (
        classify_source_level(
            title="个人博客观点",
            publisher="自媒体",
            url="https://blog.example/post",
        )
        == "C"
    )


def test_source_level_does_not_trust_report_words_in_search_metadata() -> None:
    assert (
        classify_source_level(
            title="官方项目复盘报告",
            publisher="Example 官方研究报告",
            url="https://example.com/official-report",
        )
        == "B"
    )


def test_b_level_claim_requires_independent_cross_support() -> None:
    single_b = [
        ClaimGateInput(
            id="claim-1",
            text="团队没有更新成功标准",
            source_id="source-1",
            level="B",
            support_status="VERIFIED",
        )
    ]
    same_source_duplicate = [
        *single_b,
        ClaimGateInput(
            id="claim-duplicate",
            text="团队没有更新成功标准",
            source_id="source-1",
            level="B",
            support_status="VERIFIED",
        ),
    ]
    crossed_b = [
        *single_b,
        ClaimGateInput(
            id="claim-2",
            text="团队没有更新成功标准",
            source_id="source-2",
            level="B",
            support_status="VERIFIED",
        ),
    ]

    assert usable_claim_ids(single_b) == set()
    assert usable_claim_ids(same_source_duplicate) == set()
    assert usable_claim_ids(crossed_b) == {"claim-1", "claim-2"}


def test_unsupported_and_c_level_claims_are_not_usable() -> None:
    claims = [
        ClaimGateInput(
            id="claim-a",
            text="官方报告支持的事实",
            source_id="source-a",
            level="A",
            support_status="VERIFIED",
        ),
        ClaimGateInput(
            id="claim-c",
            text="社媒帖子里的观点",
            source_id="source-c",
            level="C",
            support_status="VERIFIED",
        ),
        ClaimGateInput(
            id="claim-bad",
            text="来源没有支持的推断",
            source_id="source-s",
            level="S",
            support_status="UNSUPPORTED",
        ),
    ]

    assert usable_claim_ids(claims) == {"claim-a"}


def test_question_ready_requires_mapped_verified_claims() -> None:
    usable = {"claim-a"}

    assert question_ready(
        mapped_claim_ids=["claim-a"],
        usable_ids=usable,
        unsupported_claim_count=0,
        fact_mapping_count=1,
    )
    assert not question_ready(
        mapped_claim_ids=[],
        usable_ids=usable,
        unsupported_claim_count=0,
        fact_mapping_count=0,
    )
    assert not question_ready(
        mapped_claim_ids=["claim-a", "claim-b"],
        usable_ids=usable,
        unsupported_claim_count=0,
        fact_mapping_count=1,
    )
    assert not question_ready(
        mapped_claim_ids=["claim-a"],
        usable_ids=usable,
        unsupported_claim_count=1,
        fact_mapping_count=1,
    )


def test_normalized_question_hash_rejects_digit_only_variants() -> None:
    assert normalized_question_hash("项目延期 100 万预算如何处理") == normalized_question_hash(
        "项目延期 200 万预算如何处理"
    )


def test_bundle_credential_is_stable_for_job_retries() -> None:
    user_id = uuid4()
    job_id = uuid4()

    assert _bundle_credential(
        user_id=user_id,
        job_id=job_id,
        queries=["first query"],
    ) == _bundle_credential(
        user_id=user_id,
        job_id=job_id,
        queries=["changed query"],
    )
    assert _bundle_credential(
        user_id=user_id,
        job_id=None,
        queries=["first query"],
    ) != _bundle_credential(
        user_id=user_id,
        job_id=None,
        queries=["changed query"],
    )


def test_p08_golden_cases_match_readiness_rules() -> None:
    fixture_path = Path(__file__).parent / "golden_cases" / "p08_source_question_cases.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert {case["id"] for case in cases} == {
        "verified_a_level_claim_ready",
        "unsupported_claim_rejected",
        "single_b_level_source_rejected",
    }
    for case in cases:
        claims = [
            ClaimGateInput(
                id=claim["id"],
                text=claim["text"],
                source_id=claim["source_id"],
                level=claim["level"],
                support_status=claim["support_status"],
            )
            for claim in case["claims"]
        ]
        usable = usable_claim_ids(claims)
        ready = question_ready(
            mapped_claim_ids=case["mapped_claim_ids"],
            usable_ids=usable,
            unsupported_claim_count=case["unsupported_claim_count"],
            fact_mapping_count=case["fact_mapping_count"],
        )

        assert ready is case["expected_ready"], case["id"]
