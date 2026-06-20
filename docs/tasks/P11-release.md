# P11 报告、隐私、部署与发布验收

## Goal
- 完成个人报告、申诉/删除、备份恢复、HTTPS 部署和端到端验收。

## Context
- 必读：`AGENTS.md`、`docs/SPEC.md`、`docs/SOP.md`。
- 仅修改本任务必需文件；开始前先进入计划阶段。

## Implementation scope
- 实现本次报告、周报、缺陷趋势、历史原话证据和来源公开。
- 实现转写/重复/来源/评审申诉与处理状态。
- 实现单次训练、音频、账号全量删除；日志脱敏；备份恢复演练。
- Docker Compose + Nginx + HTTPS 部署；4 个账号真机跑通。

## Out of scope
- 应用商店发布、支付、团队排行榜、商业化管理后台。

## Done when
- [ ] P0 E2E 全链路通过。
- [ ] 删除账号后业务数据、向量、音频和 checkpoint 可验证清除。
- [ ] 备份可恢复；真实 `.env`、密钥、音频未进入 Git/日志。
- [ ] SPEC、SOP、ADR、progress 与实现一致。

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
