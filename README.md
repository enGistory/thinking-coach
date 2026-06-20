AI 语音思维训练系统开发文档包 v1.0

状态：初始开发基线，尚未开始编码。

本压缩包包含：
1. SPEC v1.0（DOCX + Markdown）
2. 开发 SOP v1.0（DOCX + Markdown）
3. Codex CLI 开发编排指南
4. 根目录与局部 AGENTS.md
5. P00-P11 分阶段任务合同
6. 项目级 .codex/config.toml、.env.example 与 .gitignore.example
7. Python 3.12.13 + uv 0.11.23 依赖基线
8. services/backend/pyproject.toml（项目版本 1.0；运行时和开发直接依赖精确版本）
9. LangGraph standalone 依赖边界：显式固定 langchain-core，不安装完整 langchain
10. services/backend/DEPENDENCIES.md、direct-pins.txt 和初始化/CI脚本

建议顺序：
- 先阅读 docs/SPEC.md、docs/SOP.md 和 docs/DEPENDENCY_POLICY.md；
- 再执行 P00；
- 在 services/backend 运行 scripts/bootstrap.ps1（Windows）或 scripts/bootstrap.sh；
- 首次真实解析后生成并提交 uv.lock；后续 CI 使用 uv lock --check + uv sync --locked。

注意：本包不会伪造 uv.lock。uv.lock 必须在可访问受信任包索引的开发机或 CI 中真实生成。
