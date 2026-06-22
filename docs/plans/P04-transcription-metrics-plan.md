# P04 云端转写与口语指标实施计划

Status: APPROVED
Approval date: 2026-06-22

## 摘要

- 业务结果：用户上传第一答音频后，系统自动发起云端 ASR 转写，保存原始稿、校正版、segment/word 时间戳和基础口语指标；前端展示片段列表，点击片段可跳到对应音频位置。
- 当前事实：`STTProvider`、`Transcript/Segment/Word`、`MockSTTProvider`、`AliyunFunASRProvider` 已存在；P03 已完成 `voice_attempt` 上传/回放和不可覆盖保护；`ai_job` 表存在但 worker 目前只是占位。
- 默认决策：上传后自动创建幂等 `TRANSCRIBE_ATTEMPT` 后台任务；转写纠错采用片段级 PATCH，保留原文、校正版、原因和差异。
- 不包含：P05 LangGraph 闭环、P06 严格评分、最终报告页、申诉流程、正式题库、完整 worker/scheduler 平台化重构、本地 ASR/GPU/新生产依赖。

## 关键变更

- 数据库新增 Alembic `0004_transcription_metrics`：
  - `attempt_transcript`：每个 `voice_attempt` 一条转写状态，保存 raw/corrected 全文、provider/model/request_id、错误码、speech metrics JSON、时间戳。
  - `transcript_segment`：按 `attempt_id + segment_index` 唯一保存 `start_ms/end_ms/raw_text/corrected_text/words_json/source`，防止重试重复写入。
  - `transcript_correction`：记录用户片段级纠错，含原文、改后文本、原因、操作者和时间。
- 后端服务：
  - 新增 `TranscriptionService`：校验 attempt 已上传、获取私有音频可访问 URL、调用现有 STT provider、事务性写入 transcript 与 segments。
  - 新增最小 `TRANSCRIBE_ATTEMPT` job 处理：上传成功后幂等入队；worker 只处理此 job 类型，失败按“初次 + 2 次重试”处理；同一 attempt 已成功则 no-op。
  - 新增 `speech_metrics` 纯 domain 规则：计算音频时长、有效语音时长、长停顿、口头禅候选、中文字符语速、重复候选、首次结论候选时间。
  - 新增私有 OSS 签名 URL 适配：Aliyun live 模式要求 OSS 配置完整，上传临时私有对象并生成短时 URL；mock 模式使用 `mock://attempt/{id}`。不记录、不返回签名 URL。
- API 与前端：
  - 新增 `GET /api/v1/attempts/{id}/transcript`，仅本人可读，返回状态、文本、segments、words、metrics。
  - 实现 SPEC 已列出的 `PATCH /api/v1/attempts/{id}/transcript-correction`，body 为 `segment_id/corrected_text/reason`；只改校正版和差异记录，不改原始稿、音频、时间戳。
  - `PUT /api/v1/attempts/{id}/audio` 成功后自动入队转写，不改变第一答不可覆盖规则。
  - `apps/web` 在现有 P03 页面上增加转写状态、片段列表和点击 seek；不做完整评审页或申诉 UI。

## 实施步骤

1. 实施前确认工作区仍干净，并切到任务分支 `codex/p04-transcription-metrics`。
2. 增加数据库模型、迁移和 repository 方法，先写迁移/幂等写入/用户隔离测试。
3. 编写 `speech_metrics` 单元测试，再实现确定性指标规则；阈值固定为 P04 常量，不新增配置项。
4. 实现 OSS/mock 音频 URL 适配和 `TranscriptionService`，用 fake/mock STT 覆盖成功、失败、重试和不重复写 segments。
5. 扩展 `AIJobRepository` 与 worker，只支持 `TRANSCRIBE_ATTEMPT`；不提前实现 LangGraph resume。
6. 增加 transcript GET 和 correction PATCH API；校验 attempt 所属用户、segment 所属 attempt、纠错原因必填、raw_text 不可变。
7. 更新前端 API 类型和 HomeView：上传后轮询 transcript 状态，展示 metrics/segments，点击片段设置 audio `currentTime` 并播放。
8. 补齐测试后运行项目要求的后端、前端、迁移和受控 live ASR 验证；最后执行 `/review` 并处理高/中优先级问题。

## 验证计划

- 后端命令：
  - `cd services/backend && uv run ruff check .`
  - `cd services/backend && uv run mypy app`
  - `cd services/backend && uv run pytest -q`
  - `cd services/backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
- 前端命令：
  - `pnpm --dir apps/web lint`
  - `pnpm --dir apps/web type-check`
  - `pnpm --dir apps/web test`
  - `pnpm --dir apps/web build`
- Live ASR 验证：
  - 仅在用户授权并设置 `RUN_LIVE_AI_TESTS=1`、真实 Aliyun/OSS 配置和非敏感中文测试录音后执行。
  - 证据要求：真实中文录音返回至少片段级时间戳，前端点击片段能回放到对应位置。
- Done when 对应证据：
  - 真实中文录音可定位到语音片段：live ASR smoke + 前端 seek 手动/浏览器验证。
  - 失败重试不重复写 segments：worker/service 集成测试断言 segment 数量和唯一约束。
  - 评审页面点击时间点能回放对应位置：HomeView P04 transcript panel 点击片段后 `audio.currentTime` 匹配 `start_ms / 1000`，并做浏览器 smoke。

## 假设、风险与停止条件

- 假设：未收到用户选择时，采用“上传后自动转写”和“片段级纠错”两个推荐默认。
- 假设：`oss2`、`dashscope` 已在依赖中，无需新增生产依赖；若实现发现必须新增依赖，停止并单独请求批准。
- 风险：Aliyun fun-asr 返回结构可能有变体；需要用 provider parser 测试覆盖样例，live smoke 失败时不得宣称 P04 完成。
- 风险：没有真实 Aliyun/OSS 配置或非敏感测试录音时，只能完成 mock/集成验证，P04 的“真实中文录音”验收需标记未完成。
- 停止条件：工作区出现无关未提交改动、需要读取真实 `.env`/生产音频、需要公开 OSS bucket、需要修改 P0 产品规则或跨入 P05/P06 范围。
- 回滚：Alembic downgrade 删除 P04 三张表；已有 `voice_attempt`、音频文件、P01/P03 Provider 与上传回放能力不受影响。
