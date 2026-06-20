# P02 数据库、账号与隔离

## Goal
- 完成 3-4 人使用所需的邀请注册、登录、训练边界和用户数据隔离。

## Context
- 必读：`AGENTS.md`、`docs/SPEC.md`、`docs/SOP.md`。
- 仅修改本任务必需文件；开始前先进入计划阶段。

## Implementation scope
- Alembic 创建 app_user、invitation、refresh_token、user_training_policy、ai_job。
- 实现 JWT、密码哈希、USER/ADMIN 最小权限。
- 所有 repository 强制 user_id 条件；补越权测试。

## Out of scope
- 第三方登录、短信、组织体系、管理员查看用户语音正文。

## Done when
- [ ] 两个用户互相无法读取或修改训练数据。
- [ ] 迁移可 upgrade/downgrade/upgrade。
- [ ] 鉴权和越权测试通过。

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
