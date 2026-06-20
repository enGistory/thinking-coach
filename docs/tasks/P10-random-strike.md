# P10 自适应随机突击与推送

## Goal
- 系统自动决定训练缺陷、题目、难度与突击时机，用户只设置时间/隐私边界。

## Context
- 必读：`AGENTS.md`、`docs/SPEC.md`、`docs/SOP.md`。
- 仅修改本任务必需文件；开始前先进入计划阶段。

## Implementation scope
- 实现缺陷优先级、已知缺陷/迁移/盲区配额、疲劳系数。
- 维护 READY 题库存；在允许窗口内随机安排 Web Push。
- 通知不暴露题型；接受、过期、延期、曝光后退出状态清晰。
- 反应力按识别/结论/结构/修正速度评估，不以秒答为优。

## Out of scope
- 用户选择题目类型或难度；固定每天同一时刻；未响应通知扣逻辑分。

## Done when
- [ ] 用户无法预知训练方向。
- [ ] 题目曝光后永久退役。
- [ ] 未接收、过期和设备通知失败不进入能力评分。

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
