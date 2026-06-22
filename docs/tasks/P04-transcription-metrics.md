# P04 云端转写与口语指标

## Goal
- 把一次回答转成带时间戳逐字稿，并计算可验证口语指标。

## Context
- 必读：`AGENTS.md`、`docs/SPEC.md`、`docs/SOP.md`。
- 仅修改本任务必需文件；开始前先进入计划阶段。

## Implementation scope
- 实现 AliyunFunASRProvider 与私有 OSS 签名 URL 适配（如需要）。
- 保存原始逐字稿、含义校正版和 segment/word 时间戳。
- 计算时长、有效语音、停顿、口头禅、语速、重复和首次结论时间的基础数据结构。
- 实现转写纠错 API，只允许纠正 STT 错误并留差异。

## Out of scope
- 根据音色判断人格/自信；自动重写用户表达。

## Done when
- [x] 真实中文录音可定位到语音片段。
- [x] 失败重试不重复写 segments。
- [x] 评审页面点击时间点能回放对应位置。

## Required verification
- [x] 后端：`uv run ruff check .`、`uv run mypy app`、`uv run pytest -q`（按任务实际目录执行）。
- [x] 前端如有改动：`pnpm lint`、`pnpm type-check`、`pnpm test`、`pnpm build`。
- [x] 数据库如有改动：Alembic upgrade/downgrade/upgrade 回归。
- [x] Prompt/Schema/规则如有改动：P04 未修改 Prompt、评审结构化输出或 Golden Case；新增 API schema 与口语指标规则由后端测试覆盖。
- [x] 执行 `/review`，修复高/中优先级问题。

## Codex completion report
- 修改文件：新增 P04 Alembic 迁移、转写/音频访问服务、逐字稿仓储、口语指标 domain、API schema 和接口、worker 任务处理、Aliyun ASR 错误映射、前端转写展示与片段 seek、P04 测试、计划与交接文档。
- 测试命令和真实结果：后端 `ruff check`、`ruff format --check`、`mypy app`、依赖策略检查、`pytest -q` 通过；Alembic upgrade/downgrade/upgrade 通过；前端 lint、type-check、test、build 通过；`uv lock --check` 与 `git diff --check` 通过；受控 live ASR smoke 已通过并返回片段级时间戳。
- 未完成项：未 push 远端；P05 LangGraph 会话、P06 严格评审、正式报告页和申诉流程不属于 P04。
- 风险：live ASR/OSS 依赖部署环境变量与私有 OSS 可访问性；真实 smoke 仅覆盖非敏感样例；存在既有 Starlette/httpx 与 Alembic deprecation warnings。
- 推荐下一任务：P05 LangGraph 会话。
