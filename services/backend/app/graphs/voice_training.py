from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, TypedDict, cast
from uuid import UUID

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.providers.contracts import (
    ChatMessage,
    LLMProvider,
    LLMStructuredRequest,
    STTProvider,
)
from app.core.config import Settings
from app.db.models import TrainingSession
from app.repositories.jobs import AIJobRepository
from app.repositories.source_questions import SourceQuestionRepository
from app.repositories.trainings import TrainingRepository
from app.services.transcription import TranscriptionService


def _configure_psycopg_event_loop_policy() -> None:
    if sys.platform != "win32":
        return
    selector_policy_factory = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy_factory is not None:
        asyncio.set_event_loop_policy(selector_policy_factory())


_configure_psycopg_event_loop_policy()

DEV_QUESTION_TEXT = (
    "开发测试题: 一个关键项目已经延期两周, 团队成员认为主要原因是需求频繁变化, "
    "业务负责人认为是技术方案判断失误。你需要在 90 秒内向上级说明当前判断、"
    "证据缺口、取舍和下一步行动。"
)
FINAL_PROMPT_TEXT = "请用 60 秒给出最终压缩回答: 先结论, 再说明依据、未知、取舍和下一步。"
FOLLOWUP_PROMPT_VERSION = "p05-followup-v1"


class TrainingState(TypedDict, total=False):
    session_id: str
    user_id: str
    current_stage: str
    first_attempt_id: str
    followup_attempt_id: str
    final_attempt_id: str
    followup_round: int
    max_followup_rounds: int
    question_text: str
    followup_text: str
    final_prompt_text: str
    error_code: str | None


class FollowupOutput(BaseModel):
    ok: bool
    message: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True)
class VoiceTrainingDeps:
    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    llm_provider: LLMProvider
    stt_provider: STTProvider


class VoiceTrainingError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def initial_training_state(
    training_session: TrainingSession,
    *,
    question_text: str | None = None,
) -> TrainingState:
    return {
        "session_id": str(training_session.id),
        "user_id": str(training_session.user_id),
        "current_stage": "WAIT_FIRST_AUDIO",
        "followup_round": 0,
        "max_followup_rounds": 1,
        "question_text": question_text or DEV_QUESTION_TEXT,
        "final_prompt_text": FINAL_PROMPT_TEXT,
        "error_code": None,
    }


async def resume_voice_training(
    *,
    deps: VoiceTrainingDeps,
    training_session: TrainingSession,
    attempt_id: UUID,
    stage: str,
    round_number: int,
) -> TrainingState:
    async with open_postgres_checkpointer(deps.settings) as checkpointer:
        graph = build_voice_training_graph(deps, checkpointer)
        config = _thread_config(training_session.thread_id)
        await _ensure_graph_started(
            deps=deps,
            graph=graph,
            config=config,
            training_session=training_session,
        )
        result = await graph.ainvoke(
            Command(
                resume={
                    "attempt_id": str(attempt_id),
                    "stage": stage,
                    "round": round_number,
                }
            ),
            config=config,
        )
    return cast(TrainingState, result)


async def load_voice_training_state(
    *,
    deps: VoiceTrainingDeps,
    thread_id: str,
) -> TrainingState:
    return await asyncio.to_thread(_load_voice_training_state_sync, deps, thread_id)


def _load_voice_training_state_sync(
    deps: VoiceTrainingDeps,
    thread_id: str,
) -> TrainingState:
    conninfo = _psycopg_conninfo(deps.settings.database_sync_url)
    with PostgresSaver.from_conn_string(conninfo) as checkpointer:
        checkpointer.setup()
        graph = build_voice_training_graph(deps, checkpointer)
        snapshot = graph.get_state(_thread_config(thread_id))
    values = getattr(snapshot, "values", {}) or {}
    return cast(TrainingState, dict(values))


async def load_voice_training_state_async(
    *,
    deps: VoiceTrainingDeps,
    thread_id: str,
) -> TrainingState:
    async with open_postgres_checkpointer(deps.settings) as checkpointer:
        graph = build_voice_training_graph(deps, checkpointer)
        snapshot = await graph.aget_state(_thread_config(thread_id))
    values = getattr(snapshot, "values", {}) or {}
    return cast(TrainingState, dict(values))


def build_voice_training_graph(
    deps: VoiceTrainingDeps,
    checkpointer: Any,
) -> Any:
    workflow = StateGraph(TrainingState)
    workflow.add_node("wait_first_audio", _wait_first_audio)
    workflow.add_node("process_first", cast(Any, _process_first_answer(deps)))
    workflow.add_node("wait_followup_audio", _wait_followup_audio)
    workflow.add_node("process_followup", cast(Any, _process_followup_answer(deps)))
    workflow.add_node("wait_final_audio", _wait_final_audio)
    workflow.add_node("process_final", cast(Any, _process_final_answer(deps)))

    workflow.add_edge(START, "wait_first_audio")
    workflow.add_edge("wait_first_audio", "process_first")
    workflow.add_edge("process_first", "wait_followup_audio")
    workflow.add_edge("wait_followup_audio", "process_followup")
    workflow.add_edge("process_followup", "wait_final_audio")
    workflow.add_edge("wait_final_audio", "process_final")
    workflow.add_edge("process_final", END)
    return workflow.compile(checkpointer=checkpointer)


@asynccontextmanager
async def open_postgres_checkpointer(settings: Settings) -> AsyncIterator[AsyncPostgresSaver]:
    conninfo = _psycopg_conninfo(settings.database_sync_url)
    async with AsyncPostgresSaver.from_conn_string(conninfo) as checkpointer:
        await checkpointer.setup()
        yield checkpointer


async def _ensure_graph_started(
    *,
    deps: VoiceTrainingDeps,
    graph: Any,
    config: dict[str, dict[str, str]],
    training_session: TrainingSession,
) -> None:
    snapshot = await graph.aget_state(config)
    if getattr(snapshot, "values", None):
        return
    question_text = await _question_text_for_session(deps, training_session)
    await graph.ainvoke(
        initial_training_state(training_session, question_text=question_text),
        config=config,
    )


def _wait_first_audio(state: TrainingState) -> TrainingState:
    resume_payload = interrupt(
        {
            "type": "FIRST_ANSWER",
            "stage": "FIRST",
            "round": 1,
            "text": state.get("question_text", DEV_QUESTION_TEXT),
        }
    )
    attempt_id = _attempt_id_from_resume(resume_payload, expected_stage="FIRST", expected_round=1)
    return {
        "first_attempt_id": attempt_id,
        "current_stage": "PROCESS_FIRST",
        "error_code": None,
    }


def _wait_followup_audio(state: TrainingState) -> TrainingState:
    resume_payload = interrupt(
        {
            "type": "FOLLOWUP_QUESTION",
            "stage": "FOLLOWUP",
            "round": 1,
            "text": state.get("followup_text", ""),
        }
    )
    attempt_id = _attempt_id_from_resume(
        resume_payload,
        expected_stage="FOLLOWUP",
        expected_round=1,
    )
    return {
        "followup_attempt_id": attempt_id,
        "current_stage": "PROCESS_FOLLOWUP",
        "error_code": None,
    }


def _wait_final_audio(state: TrainingState) -> TrainingState:
    resume_payload = interrupt(
        {
            "type": "FINAL_ANSWER",
            "stage": "FINAL",
            "round": 1,
            "text": state.get("final_prompt_text", FINAL_PROMPT_TEXT),
        }
    )
    attempt_id = _attempt_id_from_resume(resume_payload, expected_stage="FINAL", expected_round=1)
    return {
        "final_attempt_id": attempt_id,
        "current_stage": "EVALUATING",
        "error_code": None,
    }


GraphNode = Callable[[TrainingState], Awaitable[TrainingState]]


def _process_first_answer(deps: VoiceTrainingDeps) -> GraphNode:
    async def process_first(state: TrainingState) -> TrainingState:
        session_id = _uuid_from_state(state, "session_id")
        user_id = _uuid_from_state(state, "user_id")
        attempt_id = _uuid_from_state(state, "first_attempt_id")
        await _set_session_stage(deps, session_id, user_id, "PROCESS_FIRST")
        transcript_text = await _transcribe_attempt(deps, attempt_id)
        followup_text = await _generate_followup(
            deps,
            state.get("question_text", DEV_QUESTION_TEXT),
            transcript_text,
        )
        await _set_session_stage(deps, session_id, user_id, "WAIT_FOLLOWUP_AUDIO")
        return {
            "current_stage": "WAIT_FOLLOWUP_AUDIO",
            "followup_round": 1,
            "followup_text": followup_text,
            "error_code": None,
        }

    return process_first


def _process_followup_answer(deps: VoiceTrainingDeps) -> GraphNode:
    async def process_followup(state: TrainingState) -> TrainingState:
        session_id = _uuid_from_state(state, "session_id")
        user_id = _uuid_from_state(state, "user_id")
        attempt_id = _uuid_from_state(state, "followup_attempt_id")
        await _set_session_stage(deps, session_id, user_id, "PROCESS_FOLLOWUP")
        await _transcribe_attempt(deps, attempt_id)
        await _set_session_stage(deps, session_id, user_id, "WAIT_FINAL_AUDIO")
        return {
            "current_stage": "WAIT_FINAL_AUDIO",
            "final_prompt_text": FINAL_PROMPT_TEXT,
            "error_code": None,
        }

    return process_followup


def _process_final_answer(deps: VoiceTrainingDeps) -> GraphNode:
    async def process_final(state: TrainingState) -> TrainingState:
        session_id = _uuid_from_state(state, "session_id")
        user_id = _uuid_from_state(state, "user_id")
        attempt_id = _uuid_from_state(state, "final_attempt_id")
        await _set_session_stage(deps, session_id, user_id, "EVALUATING")
        await _transcribe_attempt(deps, attempt_id)
        await _enqueue_evaluation(deps, session_id, user_id)
        return {"current_stage": "EVALUATING", "error_code": None}

    return process_final


async def _transcribe_attempt(deps: VoiceTrainingDeps, attempt_id: UUID) -> str:
    async with deps.sessionmaker() as session:
        transcript = await TranscriptionService(
            session=session,
            settings=deps.settings,
            stt_provider=deps.stt_provider,
        ).transcribe_attempt(attempt_id)
        text = transcript.corrected_text.strip() or transcript.raw_text.strip()
        if not text:
            raise VoiceTrainingError("TRANSCRIPT_EMPTY", "Attempt transcript is empty")
        return text


async def _generate_followup(
    deps: VoiceTrainingDeps,
    question_text: str,
    first_answer: str,
) -> str:
    response = await deps.llm_provider.generate_structured(
        LLMStructuredRequest(
            model_slot="dialog",
            prompt_version=FOLLOWUP_PROMPT_VERSION,
            messages=[
                ChatMessage(
                    role="system",
                    content=(
                        "你是语音思维训练的追问生成器。只生成一个简短追问, "
                        "追问应要求用户补充依据、取舍或未知, 不要给参考答案。"
                    ),
                ),
                ChatMessage(
                    role="user",
                    content=(
                        f"题目: {question_text}\n"
                        f"用户第一答转写: {first_answer}\n"
                        '请返回 JSON: {"ok": true, "message": "一个追问"}'
                    ),
                ),
            ],
            temperature=deps.settings.llm_temperature_dialog,
        ),
        FollowupOutput,
    )
    output = cast(FollowupOutput, response.output)
    message = output.message.strip()
    if not output.ok or not message:
        raise VoiceTrainingError("FOLLOWUP_GENERATION_FAILED", "Follow-up output was invalid")
    return message


async def _set_session_stage(
    deps: VoiceTrainingDeps,
    session_id: UUID,
    user_id: UUID,
    stage: str,
) -> None:
    async with deps.sessionmaker() as session:
        training_session = await TrainingRepository(session).get_owned_session_for_update(
            session_id=session_id,
            user_id=user_id,
        )
        if training_session is None:
            raise VoiceTrainingError("SESSION_NOT_FOUND", "Training session was not found")
        training_session.stage = stage
        await session.commit()


async def _enqueue_evaluation(
    deps: VoiceTrainingDeps,
    session_id: UUID,
    user_id: UUID,
) -> None:
    async with deps.sessionmaker() as session:
        training_session = await TrainingRepository(session).get_owned_session_for_update(
            session_id=session_id,
            user_id=user_id,
        )
        if training_session is None:
            raise VoiceTrainingError("SESSION_NOT_FOUND", "Training session was not found")
        training_session.stage = "EVALUATING"
        await AIJobRepository(session).enqueue_evaluate_session(
            session_id=session_id,
            user_id=user_id,
        )
        await session.commit()


async def _question_text_for_session(
    deps: VoiceTrainingDeps,
    training_session: TrainingSession,
) -> str | None:
    if training_session.question_id is None:
        return None
    async with deps.sessionmaker() as session:
        question = await SourceQuestionRepository(session).get_question(
            training_session.question_id
        )
        return question.prompt if question is not None else None


def _attempt_id_from_resume(
    value: object,
    *,
    expected_stage: str,
    expected_round: int,
) -> str:
    if not isinstance(value, Mapping):
        raise VoiceTrainingError("GRAPH_RESUME_INVALID", "Resume payload must be an object")
    stage = value.get("stage")
    round_number = value.get("round")
    attempt_id = value.get("attempt_id")
    if stage != expected_stage or round_number != expected_round or not isinstance(attempt_id, str):
        raise VoiceTrainingError("GRAPH_RESUME_MISMATCH", "Resume payload did not match interrupt")
    try:
        UUID(attempt_id)
    except ValueError as exc:
        raise VoiceTrainingError("GRAPH_RESUME_INVALID", "attempt_id was not a UUID") from exc
    return attempt_id


def _uuid_from_state(state: TrainingState, key: str) -> UUID:
    value = state.get(key)
    if not isinstance(value, str):
        raise VoiceTrainingError("GRAPH_STATE_INVALID", f"State field {key} is missing")
    return UUID(value)


def _thread_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def _psycopg_conninfo(database_url: str) -> str:
    return (
        database_url.replace("postgresql+psycopg://", "postgresql://")
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
    )
