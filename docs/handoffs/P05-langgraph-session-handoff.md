# P05 LangGraph 会话交接

## 状态
- 交接状态：VERIFIED，可交接。
- 分支：`codex/p05-langgraph-session`
- 基线：`17132d7 feat: add P04 transcription metrics`
- 提交与合并状态：未提交；未执行 commit、push、merge、release。`project-handoff` 技能本身禁止 merge，且当前 P05 仍是未提交改动；若继续合并到 `dev`，需要先单独完成本地提交，再切换/合并到 `dev`。

## 业务结果
- 固定开发测试题已从单次第一答升级为“第一答 -> 动态追问 -> 最终答”的最小语音答辩闭环。
- 后端使用 LangGraph `StateGraph`、Postgres checkpointer 与稳定 `training_session.thread_id` 支持暂停和恢复。
- 用户每阶段上传音频后，由 `GRAPH_RESUME` 后台 job 推进流程；重复 resume 不重复创建业务记录或重复推进。
- 前端刷新后可从后端 `state` 恢复当前等待阶段；转写完成但图仍在处理时，会继续轮询训练状态直到进入下一等待阶段或终态。

## 主要实现范围
- Graph：新增 `services/backend/app/graphs/voice_training.py`，实现 `wait_first_audio`、`wait_followup_audio`、`wait_final_audio` 三个 interrupt/resume 点，以及第一答转写、追问生成、追问转写、最终答转写和会话完成节点。
- API：扩展训练接口，新增 `GET /api/v1/trainings/{session_id}/state` 与 `POST /api/v1/trainings/{session_id}/resume`；`create attempt` 支持 stage/round；上传接口仅确保 pending transcript，P05 正常流程由 graph 驱动转写。
- Worker：新增 `GRAPH_RESUME` job 执行路径；对 stale resume 同时检查业务 session stage 与 LangGraph checkpoint stage，避免旧 job 在下一 interrupt 误重放。
- Repository/Schema：扩展 job 类型、idempotency key 查询、训练状态查询和 P05 响应 schema。
- Frontend：扩展训练 API client；抽出 `trainingFlow.ts` 状态判断；首页支持三阶段录音、上传后 resume、pending audio 恢复、transcript polling 与 training state polling 协同。
- Tests：新增 P05 LangGraph 后端测试和前端状态流测试；补充 P04 转写回归以适配 P05 上传不再自动入队转写的路径。

## 验收证据
- `git diff --check`：通过。
- `cd services/backend && uv lock --check`：通过。
- `cd services/backend && uv sync --locked --all-groups`：通过。
- `cd services/backend && uv run python scripts/verify_dependency_policy.py`：通过。
- `cd services/backend && uv run ruff check .`：通过。
- `cd services/backend && uv run ruff format --check .`：通过。
- `cd services/backend && uv run mypy app`：通过。
- `cd services/backend && uv run pytest -q tests/test_langgraph_p05.py`：通过，`6 passed`。
- `cd services/backend && uv run pytest -q`：通过；仅剩既有 Starlette/httpx TestClient 与 Alembic `path_separator` deprecation warnings。
- `pnpm.cmd --dir apps/web lint`：通过。
- `pnpm.cmd --dir apps/web type-check`：通过。
- `pnpm.cmd --dir apps/web test`：通过，`6 files / 17 tests`。
- `pnpm.cmd --dir apps/web build`：通过。
- `make lint`：通过。
- `make typecheck`：通过。
- `make test`：通过。
- `make web-build`：通过。
- `/review`：最新 review 未发现 actionable 问题；此前发现的高优先级恢复问题均已修复并补充回归测试。

## Done When 映射
- 正常流程完成三阶段 attempt：通过。`tests/test_langgraph_p05.py` 覆盖 FIRST、FOLLOWUP、FINAL 三阶段 resume 后会话完成。
- 重复 resume 不创建重复记录：通过。`GRAPH_RESUME` idempotency key 与重复 resume 测试覆盖同一 attempt 的重复提交。
- API/worker 重启后从正确 checkpoint 恢复：通过。P05 测试覆盖同一 `thread_id`、新 graph/checkpointer 实例恢复；worker stale job 回归测试覆盖业务 stage 与 checkpoint 不一致时必须继续 replay 的场景。
- 浏览器刷新恢复：通过。前端 `trainingFlow.test.ts` 与 `HomeView` 逻辑覆盖 awaiting/processing/terminal 状态判断和轮询恢复。

## 未运行与不适用项
- 未执行 commit、push、PR、release 或生产部署。
- 未执行真实模型 smoke test：P05 测试使用 mock/fake provider；任务未要求 `RUN_LIVE_AI_TESTS=1`，且不读取真实 `.env`。
- 未执行 Alembic upgrade/downgrade/upgrade：P05 未新增业务迁移；LangGraph checkpointer 内部表由 checkpointer setup 测试覆盖，不手写 Alembic 迁移。
- 未运行 `make test-graph` / `make test-e2e`：当前 `Makefile` 未定义这两个目标；P05 graph 自动化由后端 pytest 覆盖。
- Golden Case 未运行：P05 未修改 Prompt、严格评审结构化输出、评分规则或缺陷分类。

## API、数据库、配置、依赖影响
- API：新增训练状态读取与 graph resume 接口；attempt 创建扩展为可指定 stage/round。
- 数据库：无新增业务表或 Alembic 业务迁移；运行时会通过 LangGraph Postgres checkpointer setup 管理其内部 checkpoint 表。
- 配置：未新增环境变量；graph checkpointer 使用既有 `DATABASE_SYNC_URL`，对话追问使用既有 Qwen dialog provider 配置。
- 依赖：未新增或升级生产依赖；继续使用已锁定的 `langgraph`、`langchain-core` 与 `langgraph-checkpoint-postgres`。
- 运行：P05 正常训练流依赖 API 进程、worker 进程、PostgreSQL、AI provider mock/aliyun 配置和音频存储；上传后不再由上传接口自动创建 `TRANSCRIBE_ATTEMPT` job。

## 已确认不做
- 不实现严格评分、Rubric 冻结、证据复核或报告页；留给 P06。
- 不实现缺陷画像、缺陷经验库或历史相似问题；留给 P07。
- 不实现真实来源出题、来源核验或题目防重复；留给 P08/P09。
- 不实现随机突击调度、Web Push 或生产发布；留给 P10/P11。
- 不引入完整 LangChain Agent、自由多 Agent、本地模型、GPU 依赖、Celery、Redis、Kafka、RabbitMQ 或新的生产依赖。

## 已知风险
- P05 仍使用开发测试题和固定 1 轮追问，只验证会话编排与恢复闭环，不代表正式训练题质量。
- 真实生产恢复还应在部署环境做一次 API/worker 进程重启 smoke，确认 `DATABASE_SYNC_URL`、checkpointer 内部表权限和 worker 启动顺序无误。
- 前端已覆盖状态判断与构建测试，但未做真实移动浏览器的刷新/断网/后台切换手工演练。
- Starlette/httpx 与 Alembic `path_separator` deprecation warnings 仍存在，属于既有工具链提示。

## 回滚方式
- 代码层：revert P05 提交，移除 graph、resume/state API、worker `GRAPH_RESUME` 路径和前端三阶段流程。
- 数据库层：无业务迁移需要回滚；如仅在非生产测试库中需要清理 LangGraph checkpointer 内部表，应先停用 worker/API 后按 checkpointer 官方表清单清理。
- 运行层：如 P05 graph 异常，可临时停止 `GRAPH_RESUME` worker 路径，保留 P04 上传、回放和独立转写能力。

## 下一任务建议
- 推荐进入 P06：严格评审。
- 前置条件：P05 本地提交并合并到 `dev`；开发/测试环境提供 PostgreSQL、worker、稳定 `DATABASE_SYNC_URL`；继续使用 fake provider 做自动化测试，真实模型 smoke 需用户显式授权。
