# P08 真实来源、事实原子与自动出题

## Goal
- 从可靠来源生成有完整证据映射的新题和冻结 Rubric。

## Context
- 必读：`AGENTS.md`、`docs/SPEC.md`、`docs/SOP.md`。
- 仅修改本任务必需文件；开始前先进入计划阶段。

## Implementation scope
- 实现 SearchProvider、ContentFetcher、网页/PDF解析和来源等级。
- 保存 source、snapshot_hash、claim、locator、excerpt、support_status。
- 独立 verifier 检查每个题目事实；unsupported_claim_count 必须为 0。
- 一次生成多个 QuestionCandidate，基于目标缺陷和未覆盖场景选题；答后公开来源。

## Out of scope
- 模型凭记忆编造案例；把原案例结果当唯一答案；无来源时强行出题。

## Done when
- [ ] 每个事实可定位原始证据。
- [ ] 无合格来源时不产生 READY 题。
- [ ] 题目、来源、Rubric、Prompt 版本在曝光前冻结。

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
