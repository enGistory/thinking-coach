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
- [ ] 真实中文录音可定位到语音片段。
- [ ] 失败重试不重复写 segments。
- [ ] 评审页面点击时间点能回放对应位置。

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
