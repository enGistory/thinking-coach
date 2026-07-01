# P11 报告、隐私、部署与发布验收计划

Status: APPROVED
Approval date: 2026-06-25

## 摘要

- 目标：补齐 P0 发布收口能力，包括本次报告、周报、四类申诉状态、个人数据导出、单条/账号删除、备份恢复脚本、生产 Compose + Nginx + HTTPS 配置和发布验收清单。
- 当前事实：P10 已 `VERIFIED`；工作区无跟踪文件改动；已有评审表、缺陷画像、来源公开、重复投诉、Push/随机突击和基础 Docker Compose；缺少 `report`、`weekly-reports`、删除、导出、备份恢复、生产 Nginx/HTTPS。
- 验收口径：按已确认的“代码 + 演练”执行。真实公网服务器部署、真实 `.env`、证书和生产数据操作不在实现阶段自动执行，需另行显式授权。
- 明确不做：不做应用商店发布、支付、团队榜、商业化后台；不新增生产依赖；不读取真实 `.env`；不提交证书、密钥、真实音频或生产备份。

## 关键变更

- 报告与周报：
  - 新增 `GET /api/v1/trainings/{id}/report`，返回三类分数、final score、问题证据、quote/time range、attempt/stage、历史相似缺陷、来源摘要、申诉状态；只允许本人读取。
  - 新增 `weekly_report` 表与 `GET /api/v1/me/weekly-reports`；周报由确定性 Python 汇总 completed reports、defect_profile、speech metrics 和复发/改善趋势，不调用 LLM。
  - Scheduler 增加周报生成入口；报告内容不包含人格化判断，只展示可观察行为和趋势。

- 申诉与处理状态：
  - 扩展 `appeal`：支持 `transcript`、`source`、`evaluation`、`defect_classification`，新增结构化 target JSON，保留现有缺陷申诉暂停/复核逻辑。
  - 保留 P09 `question_duplicate_complaint` 作为重复题专用通道；新增统一的训练申诉列表响应，把普通 appeal 与 duplicate complaint 合并展示处理状态。
  - 新增 admin 只读/复核接口：列出 OPEN appeals，复核 accepted/rejected；接受 `source` 或 `transcript` 申诉时将该 session report 置为 `INVALID` 并排除相关 defect occurrences，避免争议证据继续影响画像。

- 隐私、导出与删除：
  - 新增最小 JSON 导出 `GET /api/v1/me/export`：包含账号策略、训练元数据、报告、来源、缺陷画像、申诉和审计元数据；不导出音频二进制、不暴露内部密钥或签名 URL。
  - 新增 `DELETE /api/v1/me/trainings/{id}`：删除本人单条训练的 attempts、音频文件、transcripts、report/issues、defect occurrences、session checkpoint；清理孤儿 question/fingerprint/source bundle。
  - 新增 `privacy_deletion_request` 与 `privacy_audit_event`；`DELETE /api/v1/me` 仅 USER 自删，立即禁用账号并撤销 refresh token，入队 `DELETE_ACCOUNT` job。
  - Worker 处理账号删除：收集并删除音频文件，按 thread_id 清理 `checkpoint_writes`、`checkpoint_blobs`、`checkpoints`，删除用户业务数据，保留不含 PII 的 deletion proof。新增 proof-code 状态查询接口，避免删除后还要求登录。
  - 不删除 `checkpoint_migrations`，不手工修改 LangGraph 内部结构。

- 部署与运维：
  - 新增生产 Compose：postgres、api、worker、scheduler、nginx；Nginx 服务构建前端静态产物，反代 `/api/`，终止 HTTPS，HTTP 强制跳转 HTTPS。
  - 新增 `infra/env.production.example`、Nginx 配置模板和备份/恢复脚本；证书、真实 env、备份文件均保持 Git 忽略。
  - 新增 LangGraph checkpointer setup 脚本，发布命令不要求手写内部表。
  - 更新 `docs/progress.md`、P11 handoff/发布验收清单；不保存真实密钥、真实音频路径或生产 URL。

## 公共接口与数据模型

- 新增 API：
  - `GET /api/v1/trainings/{id}/report`
  - `GET /api/v1/trainings/{id}/appeals`
  - `GET /api/v1/me/weekly-reports`
  - `GET /api/v1/me/export`
  - `DELETE /api/v1/me/trainings/{id}`
  - `DELETE /api/v1/me`
  - `POST /api/v1/privacy/deletion-status`
  - `GET /api/v1/admin/appeals`
  - `POST /api/v1/admin/appeals/{id}/review`
- 数据库迁移：新增 `0010_release_privacy`，创建 `weekly_report`、`privacy_deletion_request`、`privacy_audit_event`，扩展 `appeal` 类型约束和 target 字段。
- 配置：新增备份目录、公开部署 URL、Nginx/HTTPS 示例配置；不新增 Python/Node 依赖，不刷新锁文件。

## 测试与验收

- 后端测试：
  - report API 用户隔离、证据时间点、无效 report 不展示为完成报告。
  - weekly report 幂等生成、趋势计算、空周处理、跨用户隔离。
  - 四类申诉创建、列表、admin 复核、accepted 后 report/occurrence 状态变化。
  - 单条训练删除：音频文件、transcript、report、occurrence、question vector、checkpoint 精确清除。
  - 账号删除：禁用登录、撤销 refresh、异步 job 幂等、业务表和 checkpoint 清空、proof 可查询。
  - Alembic `upgrade -> downgrade -> upgrade`。
- 前端测试：
  - API client 类型测试；HomeView 展示报告、周报、申诉状态、导出、删除训练、删除账号确认流。
  - 删除/申诉失败时显示可理解状态，不暴露敏感错误体。
- 部署/恢复演练：
  - 本地或临时测试库执行备份、恢复到新库、运行迁移和 `/health`。
  - 生产 Compose 配置检查：Nginx HTTPS、HTTP redirect、上传大小、音频目录权限、前端产物不含模型密钥。
- 必跑命令：
  - `uv lock --check`
  - `uv run python scripts/verify_dependency_policy.py`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run mypy app`
  - `uv run pytest -q`
  - `pnpm --dir apps/web lint`
  - `pnpm --dir apps/web type-check`
  - `pnpm --dir apps/web test`
  - `pnpm --dir apps/web build`
  - `git diff --check`
  - 一次独立 review，高/中优先级问题修复或记录。

## 假设、回滚与停止条件

- 假设：P11 实现期使用 mock provider 和非敏感测试数据；真实 Aliyun/Bocha/Push smoke 与 4 账号长期验收由用户提供密钥、域名、证书和明确授权后执行。
- 回滚：代码回滚到 P10；数据库可 downgrade `0010_release_privacy`；生产发布前必须先备份，若删除任务失败则保留 request 为 `FAILED` 并可重试，不静默吞掉。
- 停止条件：需要新增生产依赖、读取真实 `.env`、操作生产库/真实用户音频、真实部署服务器、不可逆删除生产数据，或发现 P11 范围会突破 P0 产品规则时立即停止并请求确认。
