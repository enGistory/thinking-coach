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
    LLMProvider,
    LLMStructuredRequest,
    ProviderError,
    SearchProvider,
    SearchRequest,
    SearchResult,
)
from app.core.config import Settings
from app.db.models import Question, QuestionSource, SourceBundle, SourceClaim
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
    QuestionWrite,
    RubricWrite,
    SourceQuestionRepository,
    SourceWrite,
)
from app.schemas.source_question import (
    ClaimExtractionResult,
    ClaimVerificationResult,
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
        search_provider: SearchProvider,
        content_fetcher: ContentFetcher,
    ) -> None:
        self._session = session
        self._settings = settings
        self._llm_provider = llm_provider
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
        return await repo.create_ready_question(
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
                normalized_hash=normalized_question_hash(candidate.prompt),
                structural_json=candidate.fingerprint,
                template_family=str(candidate.fingerprint.get("template_family", "p08")),
                source_event_id=_source_event_id(candidate),
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
    }


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
