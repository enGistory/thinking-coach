# P09 题目永不重复与换皮拦截

## Goal
- 确保历史原题、同义改写、参数/角色换皮、结构和答案骨架重复全部被拦截。

## Context
- 必读：`AGENTS.md`、`docs/SPEC.md`、`docs/SOP.md`。
- 仅修改本任务必需文件；开始前先进入计划阶段。

## Implementation scope
- 实现规范化哈希、Embedding 精确近邻、结构指纹、LLM 终审。
- 与全部历史题比较；同事件默认永久退役。
- 用户标记重复后本题作废、不计分、模板家族 denylist。
- 建立人工标注重复/非重复回归集并校准阈值。

## Out of scope
- 只靠单一余弦阈值；只更换名字/数字；回放旧题。

## Done when
- [ ] 已知换皮回归集全部拦截。
- [ ] 同缺陷复测至少改变规定的场景维度。
- [ ] 用户重复投诉能永久影响后续候选过滤。

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
