# P05 LangGraph 语音答辩闭环

> 依赖边界：使用 LangGraph standalone 与 `langchain-core` 基础运行依赖；模型调用仍走自定义 Provider，禁止引入完整 `langchain`、`langchain-openai` 或预构建 Agent。

## Goal
- 实现“问题 → 第一答 → 动态追问 → 最终答”的可暂停、恢复流程。

## Context
- 必读：`AGENTS.md`、`docs/SPEC.md`、`docs/SOP.md`。
- 仅修改本任务必需文件；开始前先进入计划阶段。

## Implementation scope
- 建立 TrainingState、StateGraph、Postgres Checkpointer。
- 实现 wait_first_audio、wait_followup_audio、wait_final_audio interrupt。
- 实现 API/worker resume 与稳定 thread_id；所有副作用拆成幂等节点。
- 实现进程和浏览器重启恢复测试。

## Out of scope
- 严格评分、来源自动出题、多个自由 Agent。

## Done when
- [ ] 正常流程完成三阶段 attempt。
- [ ] 重复 resume 不创建重复记录。
- [ ] API/worker 重启后从正确 checkpoint 恢复。

## Required verification
- [ ] 后端：`uv run ruff check .`、`uv run mypy app`、`uv run pytest -q`（按任务实际目录执行）。
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
