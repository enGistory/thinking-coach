# P07 个人缺陷经验库与训练画像

## Goal
- 将单次证据化问题累计成可解释的长期缺陷画像。

## Context
- 必读：`AGENTS.md`、`docs/SPEC.md`、`docs/SOP.md`。
- 仅修改本任务必需文件；开始前先进入计划阶段。

## Implementation scope
- 创建 defect_definition、occurrence、profile、evidence、appeal。
- 实现严重度、频率、跨场景、纠正后复发、置信度与状态转换。
- 至少 3 次、2 场景后才确认稳定缺陷；支持申诉暂停累计。
- 实现历史相似问题的具体证据展示。

## Out of scope
- 基于一次回答给人格标签；把 AI 低置信度猜测直接确认。

## Done when
- [ ] 同一问题幂等累计。
- [ ] 画像能区分 observed/confirmed/high-priority/improving/stable-improved。
- [ ] 申诉后相关 occurrence 不继续影响画像，直到复核。

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
