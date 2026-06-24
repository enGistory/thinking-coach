from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.contracts import (
    ChatMessage,
    ContentFetcher,
    ContentFetchRequest,
    ContentFetchResponse,
    EmbeddingProvider,
    EmbeddingRequest,
    LLMProvider,
    LLMStructuredRequest,
    ProviderError,
    SearchProvider,
    SearchRequest,
    SearchResult,
)
from app.core.config import Settings
from app.db.models import Question, QuestionSource, SourceBundle, SourceClaim
from app.domain.question_dedupe import (
    DEDUP_VECTOR_DIMENSIONS,
    DIRECT_REJECT_SIMILARITY,
    LLM_REVIEW_MIN_SIMILARITY,
    HistoricalQuestion,
    SimilarQuestion,
    answer_skeleton_hash,
    embedding_texts,
    hash_text,
    most_similar_questions,
    overlaps_target_defect,
    structure_comparison,
)
from app.domain.source_question import (
    ClaimGateInput,
    SourceLevel,
    SupportStatus,
    classify_source_level,
    normalized_question_hash,
    question_ready,
    usable_claim_ids,
)
from app.repositories.source_questions import (
    ClaimMappingWrite,
    ClaimWrite,
    DedupeCheckWrite,
    QuestionWrite,
    RubricWrite,
    SourceQuestionRepository,
    SourceWrite,
)
from app.schemas.source_question import (
    ClaimExtractionResult,
    ClaimVerificationResult,
    DedupeAdjudicationResult,
    QuestionCandidate,
    QuestionGenerationResult,
    RubricGenerationResult,
    SearchDirectionPlan,
)

PROMPT_VERSION = "v1.0.0"
SCHEMA_VERSION = "p08-source-question-v1"
RUBRIC_VERSION = "p08-rubric-v1"
_REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class SourceQuestionPrompt:
    name: str
    version: str
    system: str
    user: str


@dataclass(frozen=True)
class DedupePrepared:
    normalized_hash: str
    template_family: str
    source_event_id: str | None
    prompt_embedding: list[float]
    summary_embedding: list[float]
    decision_embedding: list[float]
    answer_skeleton_hash: str
    decision: str
    rejection_level: str | None
    max_similarity: float | None
    structure_change_count: int | None
    matched_question_ids: list[str]
    decision_json: dict[str, object]
    input_summary_json: dict[str, object]


class SourceQuestionError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


class SourceQuestionService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        llm_provider: LLMProvider,
        embedding_provider: EmbeddingProvider,
        search_provider: SearchProvider,
        content_fetcher: ContentFetcher,
    ) -> None:
        self._session = session
        self._settings = settings
        self._llm_provider = llm_provider
        self._embedding_provider = embedding_provider
        self._search_provider = search_provider
        self._content_fetcher = content_fetcher

    async def prepare_questions_for_user(
        self,
        *,
        user_id: UUID,
        job_id: UUID | None = None,
    ) -> list[Question]:
        repo = SourceQuestionRepository(self._session)
        target_defects = await repo.target_defects_for_user(user_id)
        bundle, directions = await self._source_bundle_and_directions(
            repo=repo,
            user_id=user_id,
            target_defects=target_defects,
            job_id=job_id,
        )
        existing = await repo.list_questions_for_bundle(bundle.id)
        if any(question.status == "READY" for question in existing):
            return existing

        sources, claims_by_id = await self._collect_sources_and_claims(
            repo,
            bundle,
            directions,
            job_id,
        )
        await repo.complete_bundle(bundle, sources)
        usable_ids = usable_claim_ids(
            ClaimGateInput(
                id=str(claim.id),
                text=claim.claim_text,
                source_id=str(source.id),
                level=cast(SourceLevel, source.level),
                support_status=cast(SupportStatus, claim.support_status),
            )
            for source in sources
            for claim in claims_by_id.values()
            if claim.source_id == source.id
        )
        if not usable_ids:
            bundle.status = "INVALID"
            await self._session.flush()
            return []

        candidates = await self._generate_candidates(
            repo,
            target_defects=target_defects,
            claims=[
                {
                    "id": str(claim.id),
                    "claim_text": claim.claim_text,
                    "locator": claim.locator,
                    "excerpt": claim.excerpt,
                }
                for claim in claims_by_id.values()
                if str(claim.id) in usable_ids
            ],
            job_id=job_id,
        )
        ready: list[Question] = []
        for candidate in candidates.candidates:
            created = await self._freeze_candidate(
                repo,
                user_id=user_id,
                bundle=bundle,
                candidate=candidate,
                usable_ids=usable_ids,
                job_id=job_id,
            )
            if created is not None:
                ready.append(created)
        if not ready:
            bundle.status = "INVALID"
            await self._session.flush()
        return ready

    async def _source_bundle_and_directions(
        self,
        *,
        repo: SourceQuestionRepository,
        user_id: UUID,
        target_defects: list[str],
        job_id: UUID | None,
    ) -> tuple[SourceBundle, SearchDirectionPlan]:
        if job_id is not None:
            credential = _bundle_credential(user_id=user_id, job_id=job_id)
            bundle = await repo.get_source_bundle_by_credential(credential)
            if bundle is not None:
                return bundle, SearchDirectionPlan(queries=list(bundle.search_queries))

            directions = await self._search_directions(repo, target_defects, job_id)
            bundle = await repo.ensure_source_bundle(
                user_id=user_id,
                credential=credential,
                target_defects=target_defects,
                search_queries=directions.queries,
                prompt_versions=_prompt_versions(),
            )
            return bundle, directions

        directions = await self._search_directions(repo, target_defects, job_id)
        credential = _bundle_credential(
            user_id=user_id,
            job_id=job_id,
            queries=directions.queries,
        )
        bundle = await repo.ensure_source_bundle(
            user_id=user_id,
            credential=credential,
            target_defects=target_defects,
            search_queries=directions.queries,
            prompt_versions=_prompt_versions(),
        )
        return bundle, directions

    async def _collect_sources_and_claims(
        self,
        repo: SourceQuestionRepository,
        bundle: SourceBundle,
        directions: SearchDirectionPlan,
        job_id: UUID | None,
    ) -> tuple[list[QuestionSource], dict[UUID, SourceClaim]]:
        seen_urls: set[str] = set()
        sources: list[QuestionSource] = []
        claims_by_id: dict[UUID, SourceClaim] = {}
        for query in directions.queries:
            results = await self._search_provider.search(SearchRequest(query=query))
            for result in results:
                url = str(result.url)
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                fetched = await self._fetch_source(result)
                if fetched is None:
                    continue
                fetched_url = fetched.url
                if fetched_url != url and fetched_url in seen_urls:
                    continue
                seen_urls.add(fetched_url)
                source = await repo.add_source(
                    bundle,
                    SourceWrite(
                        title=result.title,
                        publisher=result.source or _publisher_from_url(fetched_url),
                        url=fetched_url,
                        level=classify_source_level(
                            title=result.title,
                            publisher=result.source or "",
                            url=fetched_url,
                        ),
                        content_type=fetched.content_type,
                        published_at=_parse_datetime(result.published_at),
                        snapshot_hash=fetched.snapshot_hash,
                        extracted_characters=len(fetched.text),
                    ),
                )
                extracted = await self._extract_claims(
                    repo,
                    result,
                    fetched.text,
                    source.id,
                    job_id,
                )
                verified = await self._verify_claims(
                    repo,
                    result,
                    fetched.text,
                    extracted,
                    source.id,
                    job_id,
                )
                stored = await repo.replace_claims(source, verified)
                for claim in stored:
                    claims_by_id[claim.id] = claim
                sources.append(source)
        return sources, claims_by_id

    async def _search_directions(
        self,
        repo: SourceQuestionRepository,
        target_defects: list[str],
        job_id: UUID | None,
    ) -> SearchDirectionPlan:
        prompt = _load_prompt("search_direction")
        await repo.ensure_prompt_version(
            name=prompt.name,
            version=prompt.version,
            content_hash=_hash_text(prompt.system + "\n" + prompt.user),
            schema_version=SCHEMA_VERSION,
        )
        response = await self._llm_provider.generate_structured(
            LLMStructuredRequest(
                model_slot="question",
                prompt_version=prompt.version,
                messages=[
                    ChatMessage(role="system", content=prompt.system),
                    ChatMessage(
                        role="user",
                        content=prompt.user.format(target_defects=", ".join(target_defects)),
                    ),
                ],
                temperature=self._settings.llm_temperature_question,
            ),
            SearchDirectionPlan,
        )
        await repo.record_model_run(
            job_id=job_id,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            metadata=response.metadata,
            input_summary_json={"target_defects": target_defects},
            output_json=response.raw_json,
        )
        return cast(SearchDirectionPlan, response.output)

    async def _fetch_source(self, result: SearchResult) -> ContentFetchResponse | None:
        try:
            return await self._content_fetcher.fetch(ContentFetchRequest(url=str(result.url)))
        except ProviderError:
            return None

    async def _extract_claims(
        self,
        repo: SourceQuestionRepository,
        result: SearchResult,
        source_text: str,
        source_id: UUID,
        job_id: UUID | None,
    ) -> ClaimExtractionResult:
        prompt = _load_prompt("claim_extraction")
        await repo.ensure_prompt_version(
            name=prompt.name,
            version=prompt.version,
            content_hash=_hash_text(prompt.system + "\n" + prompt.user),
            schema_version=SCHEMA_VERSION,
        )
        response = await self._llm_provider.generate_structured(
            LLMStructuredRequest(
                model_slot="question",
                prompt_version=prompt.version,
                messages=[
                    ChatMessage(role="system", content=prompt.system),
                    ChatMessage(
                        role="user",
                        content=prompt.user.format(
                            title=result.title,
                            url=str(result.url),
                            source_text=_truncate(source_text, 8000),
                        ),
                    ),
                ],
                temperature=0.0,
            ),
            ClaimExtractionResult,
        )
        await repo.record_model_run(
            job_id=job_id,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            metadata=response.metadata,
            input_summary_json={
                "source_id": str(source_id),
                "source_chars": len(source_text),
            },
            output_json=response.raw_json,
        )
        return cast(ClaimExtractionResult, response.output)

    async def _verify_claims(
        self,
        repo: SourceQuestionRepository,
        result: SearchResult,
        source_text: str,
        extracted: ClaimExtractionResult,
        source_id: UUID,
        job_id: UUID | None,
    ) -> list[ClaimWrite]:
        prompt = _load_prompt("claim_verification")
        await repo.ensure_prompt_version(
            name=prompt.name,
            version=prompt.version,
            content_hash=_hash_text(prompt.system + "\n" + prompt.user),
            schema_version=SCHEMA_VERSION,
        )
        response = await self._llm_provider.generate_structured(
            LLMStructuredRequest(
                model_slot="verify",
                prompt_version=prompt.version,
                messages=[
                    ChatMessage(role="system", content=prompt.system),
                    ChatMessage(
                        role="user",
                        content=prompt.user.format(
                            title=result.title,
                            url=str(result.url),
                            source_text=_truncate(source_text, 8000),
                            claims=extracted.model_dump_json(),
                        ),
                    ),
                ],
                temperature=0.0,
            ),
            ClaimVerificationResult,
        )
        await repo.record_model_run(
            job_id=job_id,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            metadata=response.metadata,
            input_summary_json={
                "source_id": str(source_id),
                "claim_count": len(extracted.claims),
            },
            output_json=response.raw_json,
        )
        verified_output = cast(ClaimVerificationResult, response.output)
        verification_by_ref = {item.ref: item for item in verified_output.claims}
        writes: list[ClaimWrite] = []
        for claim in extracted.claims:
            verification = verification_by_ref.get(claim.ref)
            status = verification.support_status if verification is not None else "UNSUPPORTED"
            if claim.evidence_excerpt not in source_text:
                status = "UNSUPPORTED"
            writes.append(
                ClaimWrite(
                    claim_text=claim.claim_text,
                    locator=claim.evidence_locator,
                    excerpt=claim.evidence_excerpt,
                    support_status=status,
                    verifier_reason=verification.reason if verification is not None else "missing",
                )
            )
        return writes

    async def _generate_candidates(
        self,
        repo: SourceQuestionRepository,
        *,
        target_defects: list[str],
        claims: list[dict[str, str]],
        job_id: UUID | None,
    ) -> QuestionGenerationResult:
        prompt = _load_prompt("question_generation")
        await repo.ensure_prompt_version(
            name=prompt.name,
            version=prompt.version,
            content_hash=_hash_text(prompt.system + "\n" + prompt.user),
            schema_version=SCHEMA_VERSION,
        )
        response = await self._llm_provider.generate_structured(
            LLMStructuredRequest(
                model_slot="question",
                prompt_version=prompt.version,
                messages=[
                    ChatMessage(role="system", content=prompt.system),
                    ChatMessage(
                        role="user",
                        content=prompt.user.format(
                            target_defects=", ".join(target_defects),
                            claims=json.dumps(claims, ensure_ascii=False),
                        ),
                    ),
                ],
                temperature=self._settings.llm_temperature_question,
            ),
            QuestionGenerationResult,
        )
        await repo.record_model_run(
            job_id=job_id,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            metadata=response.metadata,
            input_summary_json={
                "target_defects": target_defects,
                "claim_count": len(claims),
            },
            output_json=response.raw_json,
        )
        return cast(QuestionGenerationResult, response.output)

    async def _freeze_candidate(
        self,
        repo: SourceQuestionRepository,
        *,
        user_id: UUID,
        bundle: SourceBundle,
        candidate: QuestionCandidate,
        usable_ids: set[str],
        job_id: UUID | None,
    ) -> Question | None:
        mapped_claim_ids = {
            str(claim_id) for mapping in candidate.fact_mappings for claim_id in mapping.claim_ids
        }
        unsupported_claim_count = len(
            {str(claim_id) for claim_id in candidate.claim_ids} - usable_ids
        )
        if not question_ready(
            mapped_claim_ids=mapped_claim_ids,
            usable_ids=usable_ids,
            unsupported_claim_count=unsupported_claim_count,
            fact_mapping_count=len(candidate.fact_mappings),
        ):
            return None
        rubric = await self._generate_rubric(repo, candidate, job_id)
        dedupe = await self._dedupe_candidate(
            repo=repo,
            user_id=user_id,
            bundle=bundle,
            candidate=candidate,
            rubric=rubric,
            job_id=job_id,
        )
        if dedupe.decision == "REJECT":
            await repo.record_dedupe_check(
                _dedupe_check_write(
                    user_id=user_id,
                    bundle_id=bundle.id,
                    question_id=None,
                    candidate=candidate,
                    dedupe=dedupe,
                )
            )
            return None
        created = await repo.create_ready_question(
            user_id=user_id,
            bundle=bundle,
            question=QuestionWrite(
                prompt=candidate.prompt,
                question_type=candidate.type,
                target_defects=candidate.target_defects,
                unsupported_claim_count=0,
                prompt_version=PROMPT_VERSION,
                expected_reasoning=candidate.expected_reasoning,
                prohibited_inferences=candidate.prohibited_inferences,
                hypothetical_assumptions=candidate.hypothetical_assumptions,
                normalized_hash=dedupe.normalized_hash,
                structural_json=candidate.fingerprint,
                template_family=dedupe.template_family,
                source_event_id=dedupe.source_event_id,
                prompt_embedding=dedupe.prompt_embedding,
                summary_embedding=dedupe.summary_embedding,
                decision_embedding=dedupe.decision_embedding,
                answer_skeleton_hash=dedupe.answer_skeleton_hash,
                dedupe_decision_json=dedupe.decision_json,
            ),
            mappings=[
                ClaimMappingWrite(
                    claim_id=claim_id,
                    usage_type="fact",
                    sentence_index=mapping.sentence_index,
                    sentence_text=mapping.sentence_text,
                )
                for mapping in candidate.fact_mappings
                for claim_id in mapping.claim_ids
            ],
            rubric=RubricWrite(
                version=RUBRIC_VERSION,
                dimensions_json={key: value for key, value in rubric.dimensions.items()},
                expected_elements_json=list(rubric.expected_elements),
                fatal_omissions_json=list(rubric.fatal_omissions),
                content_hash=_rubric_hash(rubric),
            ),
        )
        if created is not None:
            await repo.record_dedupe_check(
                _dedupe_check_write(
                    user_id=user_id,
                    bundle_id=bundle.id,
                    question_id=created.id,
                    candidate=candidate,
                    dedupe=dedupe,
                )
            )
        return created

    async def _dedupe_candidate(
        self,
        *,
        repo: SourceQuestionRepository,
        user_id: UUID,
        bundle: SourceBundle,
        candidate: QuestionCandidate,
        rubric: RubricGenerationResult,
        job_id: UUID | None,
    ) -> DedupePrepared:
        template_family = str(candidate.fingerprint.get("template_family", "p09-default"))
        source_event_id = _source_event_id(candidate)
        normalized_hash = normalized_question_hash(candidate.prompt)
        expected_reasoning = list(candidate.expected_reasoning)
        reasoning_skeleton = candidate.fingerprint.get("reasoning_skeleton")
        if isinstance(reasoning_skeleton, str) and reasoning_skeleton.strip():
            expected_reasoning.append(reasoning_skeleton)
        skeleton_hash = answer_skeleton_hash(
            expected_reasoning=expected_reasoning,
            expected_elements=rubric.expected_elements,
            fatal_omissions=rubric.fatal_omissions,
        )
        prompt_text, summary_text, decision_text = embedding_texts(
            prompt=candidate.prompt,
            structural_json=candidate.fingerprint,
            expected_reasoning=expected_reasoning,
        )
        embedding_response = await self._embedding_provider.embed_texts(
            EmbeddingRequest(
                texts=[prompt_text, summary_text, decision_text],
                dimensions=DEDUP_VECTOR_DIMENSIONS,
            )
        )
        prompt_embedding, summary_embedding, decision_embedding = [
            list(vector) for vector in embedding_response.vectors
        ]
        base: dict[str, object] = {
            "normalized_hash": normalized_hash,
            "template_family": template_family,
            "source_event_id": source_event_id,
            "candidate_hash": hash_text(candidate.prompt),
            "source_bundle_id": str(bundle.id),
            "prompt_chars": len(candidate.prompt),
            "target_defects": candidate.target_defects,
        }
        if await repo.template_family_denied(user_id=user_id, template_family=template_family):
            return _prepared_reject(
                normalized_hash=normalized_hash,
                template_family=template_family,
                source_event_id=source_event_id,
                prompt_embedding=prompt_embedding,
                summary_embedding=summary_embedding,
                decision_embedding=decision_embedding,
                answer_skeleton_hash=skeleton_hash,
                level="L0_TEMPLATE_DENYLIST",
                reason="template family is denied for this user",
                input_summary=base,
            )

        histories = await repo.list_historical_questions(user_id=user_id)
        matched_by_hash = [
            history.question_id
            for history in histories
            if history.normalized_hash == normalized_hash
        ]
        if matched_by_hash:
            return _prepared_reject(
                normalized_hash=normalized_hash,
                template_family=template_family,
                source_event_id=source_event_id,
                prompt_embedding=prompt_embedding,
                summary_embedding=summary_embedding,
                decision_embedding=decision_embedding,
                answer_skeleton_hash=skeleton_hash,
                level="L1_NORMALIZED_HASH",
                reason="normalized hash matched a historical question",
                input_summary=base,
                matched_question_ids=matched_by_hash[:10],
            )

        matched_by_event = [
            history.question_id
            for history in histories
            if source_event_id and history.source_event_id == source_event_id
        ]
        if matched_by_event:
            return _prepared_reject(
                normalized_hash=normalized_hash,
                template_family=template_family,
                source_event_id=source_event_id,
                prompt_embedding=prompt_embedding,
                summary_embedding=summary_embedding,
                decision_embedding=decision_embedding,
                answer_skeleton_hash=skeleton_hash,
                level="L1_SOURCE_EVENT",
                reason="source event is permanently retired",
                input_summary=base,
                matched_question_ids=matched_by_event[:10],
            )

        similar = most_similar_questions(
            prompt_embedding=prompt_embedding,
            summary_embedding=summary_embedding,
            decision_embedding=decision_embedding,
            histories=histories,
        )
        direct_match = next(
            (item for item in similar if item.similarity >= DIRECT_REJECT_SIMILARITY),
            None,
        )
        if direct_match is not None:
            return _prepared_reject(
                normalized_hash=normalized_hash,
                template_family=template_family,
                source_event_id=source_event_id,
                prompt_embedding=prompt_embedding,
                summary_embedding=summary_embedding,
                decision_embedding=decision_embedding,
                answer_skeleton_hash=skeleton_hash,
                level="L2_EMBEDDING",
                reason="semantic similarity is above the direct rejection threshold",
                input_summary=base,
                matched_question_ids=[item.question_id for item in similar],
                max_similarity=direct_match.similarity,
            )

        high_priority = await repo.target_requires_high_variation(
            user_id=user_id,
            defects=candidate.target_defects,
        )
        structural_rejects = [
            structure_comparison(
                candidate_structural=candidate.fingerprint,
                candidate_answer_skeleton_hash=skeleton_hash,
                history=history,
                high_priority=high_priority,
            )
            for history in histories
            if overlaps_target_defect(candidate.target_defects, history.target_defects)
        ]
        structural_rejects = [
            item
            for item in structural_rejects
            if len(item.changed_dimensions) < item.required_changes
        ]
        if structural_rejects:
            closest = structural_rejects[0]
            return _prepared_reject(
                normalized_hash=normalized_hash,
                template_family=template_family,
                source_event_id=source_event_id,
                prompt_embedding=prompt_embedding,
                summary_embedding=summary_embedding,
                decision_embedding=decision_embedding,
                answer_skeleton_hash=skeleton_hash,
                level="L3_STRUCTURE",
                reason="not enough structural dimensions changed for a same-defect retest",
                input_summary=base,
                matched_question_ids=[item.question_id for item in structural_rejects[:10]],
                structure_change_count=len(closest.changed_dimensions),
            )

        skeleton_matches = [
            history.question_id
            for history in histories
            if history.answer_skeleton_hash and history.answer_skeleton_hash == skeleton_hash
        ]
        if skeleton_matches:
            return _prepared_reject(
                normalized_hash=normalized_hash,
                template_family=template_family,
                source_event_id=source_event_id,
                prompt_embedding=prompt_embedding,
                summary_embedding=summary_embedding,
                decision_embedding=decision_embedding,
                answer_skeleton_hash=skeleton_hash,
                level="L3_ANSWER_SKELETON",
                reason="answer skeleton matched a historical question",
                input_summary=base,
                matched_question_ids=skeleton_matches[:10],
            )

        gray_matches = [item for item in similar if item.similarity >= LLM_REVIEW_MIN_SIMILARITY][
            :10
        ]
        if gray_matches:
            adjudication = await self._dedupe_adjudication(
                repo=repo,
                candidate=candidate,
                similar=gray_matches,
                histories=histories,
                job_id=job_id,
            )
            if adjudication.is_duplicate or adjudication.reusable_answer_skeleton:
                return _prepared_reject(
                    normalized_hash=normalized_hash,
                    template_family=template_family,
                    source_event_id=source_event_id,
                    prompt_embedding=prompt_embedding,
                    summary_embedding=summary_embedding,
                    decision_embedding=decision_embedding,
                    answer_skeleton_hash=skeleton_hash,
                    level="L4_LLM_ADJUDICATION",
                    reason=adjudication.reason,
                    input_summary=base,
                    matched_question_ids=[item.question_id for item in gray_matches],
                    max_similarity=gray_matches[0].similarity,
                    llm_output=adjudication.model_dump(mode="json"),
                )

        return DedupePrepared(
            normalized_hash=normalized_hash,
            template_family=template_family,
            source_event_id=source_event_id,
            prompt_embedding=prompt_embedding,
            summary_embedding=summary_embedding,
            decision_embedding=decision_embedding,
            answer_skeleton_hash=skeleton_hash,
            decision="PASS",
            rejection_level=None,
            max_similarity=similar[0].similarity if similar else None,
            structure_change_count=None,
            matched_question_ids=[item.question_id for item in similar[:10]],
            decision_json={"decision": "PASS", "reason": "dedupe checks passed"},
            input_summary_json=base,
        )

    async def _dedupe_adjudication(
        self,
        *,
        repo: SourceQuestionRepository,
        candidate: QuestionCandidate,
        similar: list[SimilarQuestion],
        histories: list[HistoricalQuestion],
        job_id: UUID | None,
    ) -> DedupeAdjudicationResult:
        prompt = _load_prompt("dedupe_adjudication")
        await repo.ensure_prompt_version(
            name=prompt.name,
            version=prompt.version,
            content_hash=_hash_text(prompt.system + "\n" + prompt.user),
            schema_version=SCHEMA_VERSION,
        )
        history_by_id = {history.question_id: history for history in histories}
        payload = [
            {
                "question_id": item.question_id,
                "similarity": round(item.similarity, 4),
                "channel": item.channel,
                "prompt": history_by_id[item.question_id].prompt,
                "fingerprint": dict(history_by_id[item.question_id].structural_json),
            }
            for item in similar
            if item.question_id in history_by_id
        ]
        response = await self._llm_provider.generate_structured(
            LLMStructuredRequest(
                model_slot="verify",
                prompt_version=prompt.version,
                messages=[
                    ChatMessage(role="system", content=prompt.system),
                    ChatMessage(
                        role="user",
                        content=prompt.user.format(
                            candidate=candidate.model_dump_json(),
                            historical_questions=json.dumps(payload, ensure_ascii=False),
                        ),
                    ),
                ],
                temperature=0.0,
            ),
            DedupeAdjudicationResult,
        )
        await repo.record_model_run(
            job_id=job_id,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            metadata=response.metadata,
            input_summary_json={
                "candidate_chars": len(candidate.prompt),
                "similar_question_ids": [item.question_id for item in similar],
            },
            output_json=response.raw_json,
        )
        return cast(DedupeAdjudicationResult, response.output)

    async def _generate_rubric(
        self,
        repo: SourceQuestionRepository,
        candidate: QuestionCandidate,
        job_id: UUID | None,
    ) -> RubricGenerationResult:
        prompt = _load_prompt("rubric_generation")
        await repo.ensure_prompt_version(
            name=prompt.name,
            version=prompt.version,
            content_hash=_hash_text(prompt.system + "\n" + prompt.user),
            schema_version=SCHEMA_VERSION,
        )
        response = await self._llm_provider.generate_structured(
            LLMStructuredRequest(
                model_slot="question",
                prompt_version=prompt.version,
                messages=[
                    ChatMessage(role="system", content=prompt.system),
                    ChatMessage(
                        role="user",
                        content=prompt.user.format(candidate=candidate.model_dump_json()),
                    ),
                ],
                temperature=0.0,
            ),
            RubricGenerationResult,
        )
        await repo.record_model_run(
            job_id=job_id,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            metadata=response.metadata,
            input_summary_json={"prompt_chars": len(candidate.prompt)},
            output_json=response.raw_json,
        )
        return cast(RubricGenerationResult, response.output)


def _load_prompt(name: str) -> SourceQuestionPrompt:
    prompt_dir = _REPO_ROOT / "prompts" / name
    return SourceQuestionPrompt(
        name=name,
        version=PROMPT_VERSION,
        system=(prompt_dir / f"{PROMPT_VERSION}.system.md").read_text(encoding="utf-8"),
        user=(prompt_dir / f"{PROMPT_VERSION}.user.md").read_text(encoding="utf-8"),
    )


def _prompt_versions() -> dict[str, str]:
    return {
        "search_direction": PROMPT_VERSION,
        "claim_extraction": PROMPT_VERSION,
        "claim_verification": PROMPT_VERSION,
        "question_generation": PROMPT_VERSION,
        "rubric_generation": PROMPT_VERSION,
        "dedupe_adjudication": PROMPT_VERSION,
    }


def _prepared_reject(
    *,
    normalized_hash: str,
    template_family: str,
    source_event_id: str | None,
    prompt_embedding: list[float],
    summary_embedding: list[float],
    decision_embedding: list[float],
    answer_skeleton_hash: str,
    level: str,
    reason: str,
    input_summary: dict[str, object],
    matched_question_ids: list[str] | None = None,
    max_similarity: float | None = None,
    structure_change_count: int | None = None,
    llm_output: dict[str, object] | None = None,
) -> DedupePrepared:
    decision_json: dict[str, object] = {
        "decision": "REJECT",
        "level": level,
        "reason": reason,
    }
    if llm_output is not None:
        decision_json["llm_output"] = llm_output
    return DedupePrepared(
        normalized_hash=normalized_hash,
        template_family=template_family,
        source_event_id=source_event_id,
        prompt_embedding=prompt_embedding,
        summary_embedding=summary_embedding,
        decision_embedding=decision_embedding,
        answer_skeleton_hash=answer_skeleton_hash,
        decision="REJECT",
        rejection_level=level,
        max_similarity=max_similarity,
        structure_change_count=structure_change_count,
        matched_question_ids=matched_question_ids or [],
        decision_json=decision_json,
        input_summary_json=input_summary,
    )


def _dedupe_check_write(
    *,
    user_id: UUID,
    bundle_id: UUID | None,
    question_id: UUID | None,
    candidate: QuestionCandidate,
    dedupe: DedupePrepared,
) -> DedupeCheckWrite:
    return DedupeCheckWrite(
        user_id=user_id,
        source_bundle_id=bundle_id,
        question_id=question_id,
        candidate_hash=hash_text(candidate.prompt),
        normalized_hash=dedupe.normalized_hash,
        template_family=dedupe.template_family,
        source_event_id=dedupe.source_event_id,
        decision=dedupe.decision,
        rejection_level=dedupe.rejection_level,
        max_similarity=dedupe.max_similarity,
        structure_change_count=dedupe.structure_change_count,
        matched_question_ids=dedupe.matched_question_ids,
        input_summary_json=dedupe.input_summary_json,
        decision_json=dedupe.decision_json,
    )


def _bundle_credential(
    *,
    user_id: UUID,
    job_id: UUID | None,
    queries: list[str] | None = None,
) -> str:
    query_basis = "" if job_id is not None else "|".join(queries or [])
    basis = f"{user_id}:{job_id or ''}:{query_basis}"
    return f"SRC-{hashlib.sha256(basis.encode('utf-8')).hexdigest()[:16]}"


def _source_event_id(candidate: QuestionCandidate) -> str | None:
    value = candidate.fingerprint.get("source_event_id")
    return value if isinstance(value, str) and value else None


def _rubric_hash(rubric: RubricGenerationResult) -> str:
    payload = json.dumps(rubric.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return _hash_text(payload)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit]


def _publisher_from_url(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0]


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
