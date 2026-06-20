# P03 语音录制、上传与回放纵向切片

## Goal
- 在手机 PWA 上完成一次可靠的语音录制、上传、保存和回放。

## Context
- 必读：`AGENTS.md`、`docs/SPEC.md`、`docs/SOP.md`。
- 仅修改本任务必需文件；开始前先进入计划阶段。

## Implementation scope
- 实现麦克风权限、MediaRecorder 格式检测、倒计时、时长/大小限制。
- 创建 training_session、voice_attempt；先建 attempt 后幂等上传。
- 保存本地临时 Blob，失败可重试；成功后清理；服务端校验归属/MIME/checksum。

## Out of scope
- 实时转写、后台录音、AI追问、完整训练流程。

## Done when
- [ ] Android/iPhone 真机能连续录制并回放。
- [ ] 网络中断后重试不产生重复 attempt。
- [ ] 第一答不可覆盖，音频不暴露公共 URL。

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
