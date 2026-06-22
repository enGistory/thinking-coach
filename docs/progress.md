# 开发进度

| 阶段 | 状态 | 分支/提交 | 完成证据 | 剩余风险 |
|---|---|---|---|---|
| P00 工程骨架 | NOT_STARTED |  |  |  |
| P01 云模型配置 | VERIFIED | codex/p01-cloud-providers | 后端 lint、format、mypy、pytest、依赖策略、mock smoke、真实 Qwen/ASR/TTS/Embedding smoke 均通过 | 真实 `.env` 需同步 `.env.example` 的非敏感 AI 配置；已暴露过的 API Key 上线前建议轮换 |
| P02 数据库与账号 | VERIFIED | codex/p02-database-auth | Alembic P02 迁移、邀请注册、登录、JWT/refresh token、USER/ADMIN 权限、训练策略 user_id 隔离、admin failed jobs 脱敏已实现；后端 lint、format、mypy、依赖策略、完整 pytest、显式 Alembic downgrade/upgrade、启动检查、diff 空白检查均通过；review 的中优先级 JWT_SECRET 启动校验问题已修复 | 未提交；存在 Starlette TestClient 与 Alembic path_separator 既有 deprecation warnings；真实生产 JWT_SECRET 需由环境变量配置 |
| P03 语音纵向切片 | VERIFIED | codex/p03-audio-slice | 后端 ruff format/check、mypy、pytest、依赖策略、Alembic downgrade/upgrade 通过；前端 lint、type-check、test、build 通过；MuMu Android 模拟器录音、上传、回放 smoke 通过；/review 发现并修复并发覆盖风险 | 未提交；MuMu 只覆盖 Android 模拟器，不等同 iPhone 或物理真机音质证明；存在既有 Starlette TestClient 与 Alembic path_separator deprecation warnings |
| P04 转写与口语指标 | NOT_STARTED |  |  |  |
| P05 LangGraph 会话 | NOT_STARTED |  |  |  |
| P06 严格评审 | NOT_STARTED |  |  |  |
| P07 缺陷经验库 | NOT_STARTED |  |  |  |
| P08 来源与出题 | NOT_STARTED |  |  |  |
| P09 永不重复 | NOT_STARTED |  |  |  |
| P10 随机突击 | NOT_STARTED |  |  |  |
| P11 发布验收 | NOT_STARTED |  |  |  |
