# P05 LangGraph 语音答辩闭环计划

Status: APPROVED  
Approval date: 2026-06-22

## Summary

- 目标：实现“开发测试题 → 第一答 → 1 轮动态追问 → 最终答”的可暂停、可恢复 LangGraph 闭环，并让浏览器刷新、API/worker 重启后能用同一 `training_session.thread_id` 继续。
- 用户可见结果：前端从单次第一答升级为最小三阶段录音流程；每阶段上传后通过后端 resume 推进，页面刷新后可恢复当前等待阶段。
- 不包含：正式来源出题、严格评分、报告、缺陷画像、TTS 播报、多轮自由 Agent、最多 2 轮追问扩展。
- 当前事实：P05 尚未开始；P01-P04 已 VERIFIED；已有 `training_session.thread_id`、`voice_attempt(session_id, stage, round)` 唯一约束、转写表和 P04 转写服务。
- 实施前置：当前是 detached HEAD，开始实现前先检查工作区并创建/切换到 `codex/p05-langgraph-session`，不提交、不推送。

## Key Changes

- 后端图编排：
  - 新增 `voice_training_graph`，使用 `StateGraph`、`interrupt()`、`Command(resume=...)`、Postgres checkpointer；`thread_id` 固定使用 `training_session.thread_id`。
  - `TrainingState` 只保存 `session_id`、`user_id`、`stage`、attempt IDs、followup 文本、错误码等小型结构化字段，不保存音频、转写全文之外的大对象、密钥或连接对象。
  - 固定 1 轮追问：`WAIT_FIRST_AUDIO -> PROCESS_FIRST -> WAIT_FOLLOWUP_AUDIO -> PROCESS_FOLLOWUP -> WAIT_FINAL_AUDIO -> COMPLETED`。
  - 动态追问通过现有 `LLMProvider.generate_structured` 的 `dialog` slot 生成，Pydantic 输出采用最小 `{ ok: bool, message: str }` 合约；测试使用 mock provider，不跑真实模型。

- 后端 API/worker：
  - 扩展 `services/backend/app/api/v1/trainings.py`：新增 `GET /api/v1/trainings/{session_id}/state` 和 `POST /api/v1/trainings/{session_id}/resume`。
  - `state` 返回当前阶段、应创建的 attempt stage/round、待展示问题或追问文本、处理状态；GET 不产生副作用。
  - `resume` 校验 attempt 属于当前用户和会话、stage/round 匹配、音频已上传，然后用 `GRAPH_RESUME` job 幂等推进图。
  - 默认采用“Graph 驱动转写”：上传接口只保存音频并确保 pending transcript；graph job 调用现有 `TranscriptionService` 完成转写，避免 P04 上传 job 与 graph 重复调用 ASR。保留 `TRANSCRIBE_ATTEMPT` worker 能力用于既有测试/独立转写路径，但 P05 正常训练流不再依赖上传自动转写。
  - `AIJobRepository` 泛化新增 `GRAPH_RESUME` idempotency key，例如 `graph_resume:{session_id}:{stage}:{round}:{attempt_id}`；重复 resume 返回同一语义结果，不创建重复 job 或 attempt。

- 数据库/checkpointer：
  - 不新增业务表；如现有 `training_session.stage` 枚举足够则不做 Alembic 业务迁移。
  - Postgres checkpointer 内部表通过 `AsyncPostgresSaver.setup()` 建立，不手写 Alembic 内部表。
  - 新增 checkpointer 初始化 helper，使用项目锁定依赖 `langgraph-checkpoint-postgres==3.1.0`；连接需满足官方要求的 setup 与行字典读取约束。

- 前端最小闭环：
  - 扩展 `apps/web/src/api/training.ts`：`createVoiceAttempt` 接收 `stage`/`round`，新增 `fetchTrainingState`、`resumeTraining`。
  - 调整 `apps/web/src/views/HomeView.vue`：登录后读取 current/state，按后端返回的等待阶段录音；上传成功后调用 resume；刷新后恢复等待追问或最终答。
  - UI 只展示开发测试题/追问/最终答提示和录音控件，不做正式题库、来源、报告或评分页面。

## Test Plan

- 后端新增/更新测试：
  - 正常流程：创建 current → FIRST 上传/resume → FOLLOWUP 上传/resume → FINAL 上传/resume，最终 `training_session.stage == COMPLETED`，三段 `voice_attempt` 均存在且可追溯。
  - 重复 resume：同一 stage/round/attempt 多次提交，只产生一个 `GRAPH_RESUME` job，不重复 attempt、不重复状态推进。
  - API/worker 重启恢复：用新 app/worker 实例和同一 `thread_id` 从 checkpointer 恢复到正确等待阶段。
  - 浏览器恢复后端依据：`GET /state` 能在 `WAIT_FOLLOWUP_AUDIO` 和 `WAIT_FINAL_AUDIO` 返回正确 payload。
  - 用户隔离：其他用户无法读取 state、创建 attempt 或 resume 不属于自己的 session/attempt。
  - 转写失败：graph 标记 `FAILED_RETRYABLE` 或保持可重试状态，不进入追问/完成，不生成评分。
  - Checkpointer setup：测试库可创建内部表，重复 setup 不破坏业务表。

- 前端新增/更新测试：
  - API 测试覆盖可变 stage/round、`state`、`resume` 请求体和鉴权头。
  - 组件或状态级测试覆盖刷新恢复：已有 token 时拉取 state，按后端 `awaiting.stage` 创建对应 attempt。
  - 上传成功后必须调用 resume；resume 失败时保留本地 pending audio，可重试且不覆盖第一答。

- 验证命令：
  - 后端：`uv lock --check`、`uv run python scripts/verify_dependency_policy.py`、`uv run ruff check .`、`uv run mypy app`、`uv run pytest -q`。
  - 若有 checkpointer 内部表 setup 或业务迁移变更：执行 Alembic upgrade/downgrade/upgrade；若无业务迁移，明确报告“未新增业务迁移，仅执行 checkpointer setup 测试”。
  - 前端：`pnpm lint`、`pnpm type-check`、`pnpm test`、`pnpm build`。
  - 最后执行独立 `/review`，高/中优先级问题必须修复或记录。

## Assumptions

- 已按用户选择纳入“最小前后端闭环”。
- 用户未返回第二个转写驱动问题的选择，默认采用推荐方案“Graph 驱动转写”，理由是最小化重复 ASR 成本和状态竞争。
- P05 固定 1 轮追问，不提前实现 2 轮配置化。
- P05 使用开发测试题和文本提示；正式来源、题目音频 TTS、Rubric 冻结和评分留给后续 P06/P08。
- 不新增生产依赖，不刷新 `uv.lock`，不读取真实 `.env`，不运行真实模型 smoke test。
