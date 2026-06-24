from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.contracts import ProviderCallMetadata
from app.db.models import (
    DefectProfile,
    ModelRun,
    PromptVersion,
    Question,
    QuestionClaimMap,
    QuestionFingerprint,
    QuestionRubric,
    QuestionSource,
    SourceBundle,
    SourceClaim,
    TrainingSession,
)
from app.domain.source_question import BOOTSTRAP_DEFECTS, SourceLevel, highest_source_level


@dataclass(frozen=True)
class SourceWrite:
    title: str
    publisher: str
    url: str
    level: str
    content_type: str
    published_at: datetime | None
    snapshot_hash: str
    extracted_characters: int


@dataclass(frozen=True)
class ClaimWrite:
    claim_text: str
    locator: str
    excerpt: str
    support_status: str
    verifier_reason: str


@dataclass(frozen=True)
class QuestionWrite:
    prompt: str
    question_type: str
    target_defects: list[str]
    unsupported_claim_count: int
    prompt_version: str
    expected_reasoning: list[str]
    prohibited_inferences: list[str]
    hypothetical_assumptions: list[str]
    normalized_hash: str
    structural_json: dict[str, object]
    template_family: str
    source_event_id: str | None


@dataclass(frozen=True)
class ClaimMappingWrite:
    claim_id: UUID
    usage_type: str
    sentence_index: int
    sentence_text: str


@dataclass(frozen=True)
class RubricWrite:
    version: str
    dimensions_json: dict[str, object]
    expected_elements_json: list[str]
    fatal_omissions_json: list[str]
    content_hash: str


@dataclass(frozen=True)
class ProvenanceBundle:
    training_session: TrainingSession
    question: Question
    source_bundle: SourceBundle
    sources: list[QuestionSource]
    claims_by_source: dict[UUID, list[SourceClaim]]
    mappings: list[QuestionClaimMap]


class SourceQuestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def target_defects_for_user(self, user_id: UUID, limit: int = 3) -> list[str]:
        result = await self._session.execute(
            select(DefectProfile.defect_code)
            .where(DefectProfile.user_id == user_id)
            .order_by(DefectProfile.priority.desc(), DefectProfile.last_seen_at.desc().nullslast())
            .limit(limit)
        )
        defects = [str(code) for code in result.scalars().all()]
        return defects or list(BOOTSTRAP_DEFECTS)

    async def ensure_source_bundle(
        self,
        *,
        user_id: UUID,
        credential: str,
        target_defects: list[str],
        search_queries: list[str],
        prompt_versions: dict[str, str],
    ) -> SourceBundle:
        await self._session.execute(
            insert(SourceBundle)
            .values(
                user_id=user_id,
                credential=credential,
                status="DRAFT",
                target_defects=target_defects,
                search_queries=search_queries,
                source_count=0,
                prompt_versions_json=prompt_versions,
            )
            .on_conflict_do_nothing(index_elements=["credential"])
        )
        result = await self._session.execute(
            select(SourceBundle).where(SourceBundle.credential == credential)
        )
        bundle = result.scalar_one_or_none()
        if bundle is None:
            raise RuntimeError("source bundle upsert did not return a row")
        return bundle

    async def get_source_bundle_by_credential(self, credential: str) -> SourceBundle | None:
        result = await self._session.execute(
            select(SourceBundle).where(SourceBundle.credential == credential)
        )
        return result.scalar_one_or_none()

    async def list_questions_for_bundle(self, bundle_id: UUID) -> list[Question]:
        result = await self._session.execute(
            select(Question)
            .where(Question.source_bundle_id == bundle_id)
            .order_by(Question.created_at)
        )
        return list(result.scalars().all())

    async def add_source(self, bundle: SourceBundle, source: SourceWrite) -> QuestionSource:
        await self._session.execute(
            insert(QuestionSource)
            .values(
                source_bundle_id=bundle.id,
                title=source.title,
                publisher=source.publisher,
                url=source.url,
                level=source.level,
                content_type=source.content_type,
                published_at=source.published_at,
                snapshot_hash=source.snapshot_hash,
                extracted_characters=source.extracted_characters,
                fetch_status="SUCCEEDED",
            )
            .on_conflict_do_nothing(index_elements=["source_bundle_id", "url"])
        )
        result = await self._session.execute(
            select(QuestionSource).where(
                QuestionSource.source_bundle_id == bundle.id,
                QuestionSource.url == source.url,
            )
        )
        stored = result.scalar_one_or_none()
        if stored is None:
            raise RuntimeError("question source upsert did not return a row")
        return stored

    async def replace_claims(
        self,
        source: QuestionSource,
        claims: list[ClaimWrite],
    ) -> list[SourceClaim]:
        existing = await self._session.execute(
            select(SourceClaim).where(SourceClaim.source_id == source.id)
        )
        for existing_claim in existing.scalars().all():
            await self._session.delete(existing_claim)
        await self._session.flush()
        stored: list[SourceClaim] = []
        for claim_write in claims:
            row = SourceClaim(
                source_id=source.id,
                claim_text=claim_write.claim_text,
                locator=claim_write.locator,
                excerpt=claim_write.excerpt,
                support_status=claim_write.support_status,
                verifier_reason=claim_write.verifier_reason,
            )
            self._session.add(row)
            stored.append(row)
        await self._session.flush()
        return stored

    async def complete_bundle(self, bundle: SourceBundle, sources: list[QuestionSource]) -> None:
        levels: list[SourceLevel] = []
        for source in sources:
            if source.level in {"S", "A", "B", "C"}:
                levels.append(cast(SourceLevel, source.level))
        bundle.source_count = len(sources)
        bundle.highest_source_level = highest_source_level(levels) if levels else None
        bundle.status = "READY" if sources else "INVALID"
        await self._session.flush()

    async def normalized_hash_exists(self, normalized_hash: str) -> bool:
        result = await self._session.execute(
            select(QuestionFingerprint.id).where(
                QuestionFingerprint.normalized_hash == normalized_hash
            )
        )
        return result.scalar_one_or_none() is not None

    async def create_ready_question(
        self,
        *,
        user_id: UUID,
        bundle: SourceBundle,
        question: QuestionWrite,
        mappings: list[ClaimMappingWrite],
        rubric: RubricWrite,
    ) -> Question | None:
        if await self.normalized_hash_exists(question.normalized_hash):
            return None
        row = Question(
            user_id=user_id,
            source_bundle_id=bundle.id,
            prompt=question.prompt,
            type=question.question_type,
            target_defects=question.target_defects,
            status="READY",
            exposed_count=0,
            unsupported_claim_count=question.unsupported_claim_count,
            prompt_version=question.prompt_version,
            expected_reasoning_json=question.expected_reasoning,
            prohibited_inferences_json=question.prohibited_inferences,
            hypothetical_assumptions_json=question.hypothetical_assumptions,
            ready_at=datetime.now(UTC),
        )
        self._session.add(row)
        await self._session.flush()
        self._session.add(
            QuestionFingerprint(
                question_id=row.id,
                normalized_hash=question.normalized_hash,
                structural_json=question.structural_json,
                template_family=question.template_family,
                source_event_id=question.source_event_id,
            )
        )
        self._session.add_all(
            [
                QuestionClaimMap(
                    question_id=row.id,
                    claim_id=mapping.claim_id,
                    usage_type=mapping.usage_type,
                    sentence_index=mapping.sentence_index,
                    sentence_text=mapping.sentence_text,
                )
                for mapping in mappings
            ]
        )
        self._session.add(
            QuestionRubric(
                training_session_id=None,
                question_id=row.id,
                version=rubric.version,
                dimensions_json=rubric.dimensions_json,
                expected_elements_json=rubric.expected_elements_json,
                fatal_omissions_json=rubric.fatal_omissions_json,
                content_hash=rubric.content_hash,
            )
        )
        await self._session.flush()
        return row

    async def claim_ready_question_for_user(self, user_id: UUID) -> Question | None:
        result = await self._session.execute(
            select(Question)
            .where(
                Question.user_id == user_id,
                Question.status == "READY",
                Question.exposed_count == 0,
            )
            .order_by(Question.ready_at, Question.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mark_question_exposed(self, question: Question) -> None:
        question.status = "EXPOSED"
        question.exposed_count += 1
        question.exposed_at = datetime.now(UTC)
        await self._session.flush()

    async def get_question(self, question_id: UUID) -> Question | None:
        return await self._session.get(Question, question_id)

    async def get_source_bundle_for_question(self, question_id: UUID) -> SourceBundle | None:
        result = await self._session.execute(
            select(SourceBundle)
            .join(Question, Question.source_bundle_id == SourceBundle.id)
            .where(Question.id == question_id)
        )
        return result.scalar_one_or_none()

    async def get_question_rubric(self, question_id: UUID) -> QuestionRubric | None:
        result = await self._session.execute(
            select(QuestionRubric).where(QuestionRubric.question_id == question_id)
        )
        return result.scalar_one_or_none()

    async def get_owned_provenance(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
    ) -> ProvenanceBundle | None:
        session_result = await self._session.execute(
            select(TrainingSession, Question, SourceBundle)
            .join(Question, TrainingSession.question_id == Question.id)
            .join(SourceBundle, Question.source_bundle_id == SourceBundle.id)
            .where(
                TrainingSession.id == session_id,
                TrainingSession.user_id == user_id,
                TrainingSession.stage == "COMPLETED",
            )
        )
        row = session_result.one_or_none()
        if row is None:
            return None
        training_session, question, bundle = row
        sources = list(
            (
                await self._session.execute(
                    select(QuestionSource)
                    .where(QuestionSource.source_bundle_id == bundle.id)
                    .order_by(QuestionSource.level, QuestionSource.created_at)
                )
            ).scalars()
        )
        claims = list(
            (
                await self._session.execute(
                    select(SourceClaim)
                    .join(QuestionSource, SourceClaim.source_id == QuestionSource.id)
                    .where(QuestionSource.source_bundle_id == bundle.id)
                    .order_by(SourceClaim.created_at, SourceClaim.id)
                )
            ).scalars()
        )
        mappings = list(
            (
                await self._session.execute(
                    select(QuestionClaimMap)
                    .where(QuestionClaimMap.question_id == question.id)
                    .order_by(QuestionClaimMap.sentence_index)
                )
            ).scalars()
        )
        claims_by_source: dict[UUID, list[SourceClaim]] = {}
        for claim in claims:
            claims_by_source.setdefault(claim.source_id, []).append(claim)
        return ProvenanceBundle(
            training_session=training_session,
            question=question,
            source_bundle=bundle,
            sources=sources,
            claims_by_source=claims_by_source,
            mappings=mappings,
        )

    async def ensure_prompt_version(
        self,
        *,
        name: str,
        version: str,
        content_hash: str,
        schema_version: str,
    ) -> PromptVersion:
        await self._session.execute(
            insert(PromptVersion)
            .values(
                name=name,
                version=version,
                content_hash=content_hash,
                schema_version=schema_version,
                active=True,
            )
            .on_conflict_do_nothing(index_elements=["name", "version"])
        )
        result = await self._session.execute(
            select(PromptVersion).where(
                PromptVersion.name == name,
                PromptVersion.version == version,
            )
        )
        prompt_version = result.scalar_one_or_none()
        if prompt_version is None:
            raise RuntimeError("prompt version upsert did not return a row")
        return prompt_version

    async def record_model_run(
        self,
        *,
        job_id: UUID | None,
        prompt_name: str,
        prompt_version: str,
        metadata: ProviderCallMetadata,
        input_summary_json: dict[str, object],
        output_json: dict[str, object],
    ) -> ModelRun:
        model_run = ModelRun(
            job_id=job_id,
            report_id=None,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            provider=metadata.provider,
            model=metadata.model,
            request_id=metadata.request_id,
            latency_ms=metadata.latency_ms,
            input_tokens=metadata.usage.input_tokens,
            output_tokens=metadata.usage.output_tokens,
            input_characters=metadata.usage.input_characters,
            output_characters=metadata.usage.output_characters,
            structured_ok=metadata.structured_ok,
            error_code=metadata.error_code,
            input_summary_json=input_summary_json,
            output_json=output_json,
        )
        self._session.add(model_run)
        await self._session.flush()
        return model_run
