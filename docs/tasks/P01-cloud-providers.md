# P01 阿里云云模型配置与 Provider

## Goal
- 建立全云 AI Provider 契约、环境变量加载和可替换 Mock。

## Context
- 必读：`AGENTS.md`、`docs/SPEC.md`、`docs/SOP.md`。
- 仅修改本任务必需文件；开始前先进入计划阶段。

## Implementation scope
- 实现 Settings 启动校验与 Secret 脱敏。
- 定义 LLM/STT/TTS/Embedding/Search Provider 协议。
- 实现 AliyunQwenProvider 的结构化输出最小调用；为四类 Provider 建 Mock。
- 提供用户手工运行的 smoke test 脚本。

## Out of scope
- 把真实 API Key 写入代码或测试；本地模型；业务 Prompt。

## Done when
- [ ] 无 Key 时启动给出明确错误或按 mock 模式启动。
- [ ] 单元测试完全不访问真实 API。
- [ ] 手工 smoke test 可分别验证 Qwen、ASR、TTS、Embedding，输出不含密钥。

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
