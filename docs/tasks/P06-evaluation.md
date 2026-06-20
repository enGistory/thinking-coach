# P06 严格证据化评审

## Goal
- 实现逻辑、口语、追问应变三类独立评审，并保证每条批评可追溯。

## Context
- 必读：`AGENTS.md`、`docs/SPEC.md`、`docs/SOP.md`。
- 仅修改本任务必需文件；开始前先进入计划阶段。

## Implementation scope
- 冻结 question_rubric；实现 AnswerStructure、LogicReview、LogicIssue、EvidenceVerification Schema。
- 拆分结构提取、逻辑初评、口语统计、应变评审、证据复核节点。
- 实现 Python 权重与硬封顶规则；模型不得直接给最终总分。
- 保存 quote、start/end、confidence、missing_information 和 correction_rule。

## Out of scope
- 人格、智商、音色、情绪稳定性或领导力推断。

## Done when
- [ ] 所有负面问题有逐字稿原句和有效时间点。
- [ ] 不存在 quote 的批评被 verifier 拒绝。
- [ ] 逻辑/口语/应变分数独立；封顶规则有单元测试和 Golden Case。

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
