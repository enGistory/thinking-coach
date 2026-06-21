# P02 数据库、账号与隔离交接

## 状态
- 交接状态：VERIFIED，可交接。
- 分支：`codex/p02-database-auth`
- 基线：`c82c969 P01 云端模型 Provider 配置`
- 提交状态：未提交；未执行 commit、push、merge、release。

## 业务结果
- 完成 3-4 人使用所需的账号基础能力：管理员创建邀请、用户接受邀请注册、登录、刷新令牌、登出。
- 建立最小 `USER` / `ADMIN` 权限边界。
- 训练策略以当前登录用户的 `user_id` 为隔离条件，两个用户不能读取或修改彼此训练策略。
- 管理员失败任务接口只暴露脱敏后的任务状态与错误码，不暴露用户原始回答正文。

## 主要实现范围
- 数据库迁移：`app_user`、`invitation`、`refresh_token`、`user_training_policy`、`ai_job`。
- 后端模型与仓储：SQLAlchemy Base/models、用户、邀请、刷新令牌、训练策略、失败任务仓储。
- 鉴权安全：密码哈希、JWT access token、refresh token 哈希存储、刷新令牌轮换与注销。
- API：`/api/v1/auth/*`、`/api/v1/invitations/accept`、`/api/v1/admin/invitations`、`/api/v1/me/training-policy`、`/api/v1/admin/jobs/failed`。
- 启动配置：应用启动时校验 `JWT_SECRET`，避免鉴权接口运行期才失败。
- CI：增加 PostgreSQL/pgvector 测试服务及 P02 所需测试环境变量。

## 验收证据
- `uv sync --locked --all-groups`：通过，`Checked 136 packages`。
- `uv lock --check`：通过。
- `uv run python scripts/verify_dependency_policy.py`：通过。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：通过，52 files already formatted。
- `uv run mypy app`：通过，43 个源文件无类型错误。
- 使用临时 `pgvector/pgvector:pg16` 测试库运行 `uv run pytest -q`：通过，33 passed。
- 同一临时测试库显式运行：
  - `uv run alembic downgrade base`：通过。
  - `uv run alembic upgrade head`：通过。
  - `uv run alembic downgrade -1`：通过。
  - `uv run alembic upgrade head`：通过。
- `uv run python -c "... TestClient(create_app()) ..."`：通过，`startup ok`。
- `git diff --check`：通过。

## Done When 映射
- 两个用户互相无法读取或修改训练数据：通过。`tests/test_auth_p02.py` 覆盖两个用户训练策略隔离；`TrainingPolicyRepository` 强制按 `user_id` 查询和更新。
- 迁移可 upgrade/downgrade/upgrade：通过。`tests/test_migrations_p02.py` 覆盖，且已额外显式运行 Alembic 升降级。
- 鉴权和越权测试通过：通过。覆盖登录、邀请、普通用户禁止 admin、邀请码复用失败、refresh token 轮换、登出失效、禁用用户不可登录、失败任务脱敏。
- review 高/中优先级问题处理：通过。已修复 `[P2] JWT_SECRET 未启动校验`，并补充配置与 startup 回归测试。

## 未运行与不适用项
- 前端 `pnpm lint/type-check/test/build`：未运行。本任务无 `apps/` 前端变更。
- Golden Case：未运行。本任务未修改 Prompt、AI 结构化评审输出或评分规则。
- 真实 AI smoke test：未运行。P02 不涉及真实模型调用，且项目规则禁止默认读取真实 `.env` 或密钥。

## API、数据库、配置、依赖影响
- API：新增账号、邀请、个人训练策略和管理员失败任务接口。
- 数据库：新增 P02 五张业务表和索引；迁移可回滚。
- 配置：新增/使用 `JWT_SECRET`、`JWT_ACCESS_MINUTES`、refresh token 天数等 Settings；启动时要求 `JWT_SECRET` 已配置。
- 依赖：P02 使用既有锁定依赖中的 SQLAlchemy、Alembic、PyJWT、pwdlib、email-validator 等；依赖策略检查通过。
- 运行：测试和 CI 需要 PostgreSQL + pgvector；真实部署必须通过环境变量提供非占位 JWT secret。

## 已确认不做
- 不做第三方登录、短信登录、组织体系。
- 不允许管理员查看用户语音正文或详细回答。
- 不实现 P03 语音上传/录音切片。
- 不引入本地模型、GPU 依赖、Redis/Celery/Kafka/RabbitMQ 或微服务拆分。

## 已知风险
- Starlette `TestClient` deprecation warning 仍存在，属于既有测试工具链提示。
- Alembic `path_separator` deprecation warning 仍存在，属于配置兼容提示。
- 当前所有 P02 变更仍未提交，后续合并前需人工检查 diff 并提交。
- 生产环境必须设置强 `JWT_SECRET`；不得使用示例或测试 secret。

## 回滚方式
- 代码层：在未提交状态下，可丢弃 P02 相关未提交改动；若已提交，则 revert 对应 P02 提交。
- 数据库层：执行 `uv run alembic downgrade 0001_enable_pgvector` 回退 P02 迁移。
- 配置层：移除 P02 新增运行入口前，确认没有线上流量依赖新增 auth/API。

## 下一任务建议
- 推荐进入 P03：语音纵向切片。
- P03 前置条件：P02 提交入库；部署/本地环境提供 PostgreSQL、pgvector、`JWT_SECRET`；继续避免读取真实 `.env` 和真实用户音频。
