# P00 工程骨架与约束

## Goal
- 建立可启动的 Monorepo、基础 CI、统一配置和 Codex 指令层。

## Context
- 必读：`AGENTS.md`、`docs/SPEC.md`、`docs/SOP.md`。
- 仅修改本任务必需文件；开始前先进入计划阶段。

## Implementation scope
- 创建 Vue3 PWA、FastAPI、PostgreSQL/pgvector、Docker Compose 骨架。
- 固定 Python 3.12.13 与 uv 0.11.23，采用包内 `services/backend/pyproject.toml` 精确依赖基线。
- 在真实可联网环境运行 `uv lock` 并提交 `services/backend/uv.lock`；禁止伪造或手写锁文件。
- 建立 root/nested AGENTS.md、docs、ADR、统一错误响应、request_id、健康检查。
- 配置 Ruff、Mypy、Pytest、ESLint、TypeScript、前端 build。

## Out of scope
- 任何业务页面、真实模型调用、LangGraph 业务图。

## Done when
- [ ] 前后端可启动；`/api/v1/health` 同时检查 app/database/audio_root。
- [ ] `.python-version` 为 3.12.13，`pyproject.toml` 中所有直接依赖均有精确版本。
- [ ] `langchain-core==1.4.8`、`langgraph==1.2.6` 与 `langgraph-checkpoint-postgres==3.1.0` 存在；完整 `langchain` / `langchain-openai` 不存在。
- [ ] `uv.lock` 已真实生成并提交；`uv lock --check` 与 `uv sync --locked --all-groups` 通过。
- [ ] `uv run python scripts/verify_dependency_policy.py` 通过，未出现本地模型/GPU依赖。
- [ ] Docker Compose 能启动 postgres/api/worker/scheduler/web。
- [ ] 后端 lint/type/test 与前端 lint/type/build 全通过。

## Required verification
- [ ] 工具链：`uv --version`、`uv lock --check`、`uv sync --locked --all-groups`。
- [ ] 依赖策略：`uv run python scripts/verify_dependency_policy.py`。
- [ ] 后端：`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app`、`uv run pytest -q`（按任务实际目录执行）。
- [ ] 前端如有改动：`pnpm lint`、`pnpm type-check`、`pnpm test`、`pnpm build`。
- [ ] 数据库如有改动：Alembic upgrade/downgrade/upgrade 回归。
- [ ] Prompt/Schema/规则如有改动：Golden Case 回归。
- [ ] 执行 `/review`，修复高/中优先级问题。

## Codex completion report
- 修改文件：
- 测试命令和真实结果：
- 未完成项：
- 风险：
- 推荐下一任务：
