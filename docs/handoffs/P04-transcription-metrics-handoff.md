# P04 云端转写与口语指标交接

## 状态
- 交接状态：VERIFIED，可交接。
- 分支：`codex/p04-transcription-metrics`
- 基线：`ffe2c33 feat: 完成 P03 语音录制上传回放`
- 合并状态：按用户本次指令执行本地提交并合并到 `dev`；不执行 push、release 或生产部署。

## 业务结果
- 用户上传第一答音频后，系统会幂等创建 `TRANSCRIBE_ATTEMPT` 后台任务。
- 后端可通过私有 OSS 临时签名 URL 调用 Aliyun fun-asr，保存原始逐字稿、校正版、segment/word 时间戳和基础口语指标。
- 转写失败支持可恢复重试；未耗尽重试前 transcript 不会提前进入终态失败。
- 用户可读取自己的 transcript，并通过片段级纠错 API 修正 STT 错误；纠错留痕且不允许把原回答改写成新答案。
- 前端在现有训练页展示转写状态、口语指标和片段列表，点击片段可跳转音频回放位置。

## 主要实现范围
- 数据库迁移：新增 `attempt_transcript`、`transcript_segment`、`transcript_correction` 三张表及唯一约束/索引。
- 后端模型与仓储：新增 transcript 相关 SQLAlchemy model、仓储读写、幂等 segment upsert、片段纠错留痕、纠错长度约束。
- 后端服务：新增 `AudioAccess` 与 `TranscriptionService`，支持 mock URL、Aliyun OSS 临时私有对象、成功写入、失败标记和清理。
- Worker：实现 `TRANSCRIBE_ATTEMPT` job 领取、过期 RUNNING 回收、初次 + 2 次重试、最终失败状态同步。
- Provider：Aliyun fun-asr 保留上游错误码，不在异常或日志中暴露签名 URL。
- API：扩展音频上传后入队；新增 transcript 读取与 transcript correction patch。
- 前端：扩展训练 API 类型；新增 transcript 轮询、指标展示、segments 列表和片段 seek 工具。
- 测试：覆盖口语指标、转写服务、重试幂等、纠错约束、Aliyun 错误映射、前端 API 与 seek 行为。

## 验收证据
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：通过。
- `uv run mypy app`：通过。
- `uv run python scripts\verify_dependency_policy.py`：通过。
- `TEST_DATABASE_URL=postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking_test?ssl=disable uv run pytest -q`：通过，`50 passed, 2 skipped`。
- 使用临时验证库执行 Alembic `upgrade head`、`downgrade -1`、再次 `upgrade head`：通过。
- `pnpm.cmd --dir apps/web lint`：通过。
- `pnpm.cmd --dir apps/web type-check`：通过。
- `pnpm.cmd --dir apps/web test`：通过，`5 files / 12 tests`。
- `pnpm.cmd --dir apps/web build`：通过。
- `uv lock --check`：通过。
- `git diff --check`：通过。
- 前端 source/dist secret keyword scan：无命中。
- 受控 live ASR smoke：通过；Aliyun fun-asr 返回 2 个带时间戳 segment，首段约 `0.20s -> 3.36s`；OSS/local 临时对象清理正常。

## Done When 映射
- 真实中文录音可定位到语音片段：通过。受控 live ASR smoke 返回片段级时间戳；前端 seek 工具按 `start_ms / 1000` 定位。
- 失败重试不重复写 segments：通过。仓储唯一约束和 upsert 成功路径覆盖；worker retry 测试验证重试成功后不会重复 segments。
- 评审页面点击时间点能回放对应位置：通过。P04 暂沿用训练页 transcript panel，前端 `playbackSeek` 单元测试覆盖点击片段设置 `audio.currentTime`。

## 未运行与不适用项
- 未执行 push、PR、release 或生产部署。
- 本轮交接未再次读取真实 `.env`，未再次执行 live ASR；沿用用户授权后的受控 smoke 证据。
- Golden Case 未运行：P04 未修改 Prompt、评审结构化输出或评分 Golden Case；新增 API schema 与口语指标规则由后端测试覆盖。

## API、数据库、配置、依赖影响
- API：新增/扩展 transcript 读取、转写纠错、音频上传后自动入队。
- 数据库：新增 P04 三张 transcript/correction 表；迁移已验证可回滚。
- 配置：live ASR 依赖既有 Aliyun/DashScope/OSS 环境变量；未新增生产配置项。
- 依赖：未新增或升级生产依赖；依赖策略和锁文件检查通过。
- 运行：正式环境 OSS bucket 应保持私有，只生成短时签名 URL；不得记录或返回签名 URL。

## 已确认不做
- 不实现 P05 LangGraph 会话恢复、interrupt/resume 或追问编排。
- 不实现 P06 严格评审、Evidence Verifier、评分或缺陷确认。
- 不实现正式报告页、申诉流程、题库、来源核验或查重。
- 不引入本地 ASR/GPU/模型权重、Celery、Redis、Kafka、RabbitMQ 或新的生产依赖。

## 已知风险
- live ASR 成功依赖线上 Aliyun 与 OSS 配置、bucket 权限、签名 URL 有效期和音频格式；生产部署前应再做一次受控 smoke。
- 真实 smoke 只覆盖一段非敏感中文测试音频，不代表所有设备、格式和噪声环境。
- Starlette/httpx 与 Alembic `path_separator` deprecation warnings 仍存在，属于既有工具链提示。
- P04 仅提供转写纠错边界，不处理后续评审引用纠错稿的完整工作流；该部分留给 P05/P06/P10。

## 回滚方式
- 代码层：revert P04 本地提交或从 `dev` 回滚对应 merge。
- 数据库层：执行 Alembic `downgrade -1` 回滚 `0004_transcription_metrics`，删除 P04 三张表。
- 配置层：无需移除新增生产配置；如 live ASR 异常，可暂停 `TRANSCRIBE_ATTEMPT` worker 或禁用相关 job 入口。
- 数据层：P04 表回滚会删除 transcript、segments 和 correction；P03 `voice_attempt` 与音频上传回放能力不受影响。

## 下一任务建议
- 推荐进入 P05：LangGraph 会话。
- 前置条件：P04 提交并合并到 `dev`；开发/测试环境提供 PostgreSQL、pgvector、JWT_SECRET；如验证 live ASR，继续使用非敏感测试录音和显式授权的环境变量。
