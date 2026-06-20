# Backend dependency bootstrap

首次开发先阅读：

- `../../docs/DEPENDENCY_POLICY.md`
- `DEPENDENCIES.md`
- `pyproject.toml`

Windows：

```powershell
./scripts/bootstrap.ps1
```

Linux、macOS 或 WSL：

```bash
./scripts/bootstrap.sh
```

首次成功后必须提交 `uv.lock`。日常开发和 CI 只允许使用锁定模式：

```bash
uv lock --check
uv sync --locked --all-groups
```

## LangChain 依赖边界

本后端使用 LangGraph standalone。`langchain-core==1.4.8` 为显式基础运行依赖；完整 `langchain` 与 `langchain-openai` 不安装。LLM 调用走自定义 Provider + OpenAI/DashScope SDK。
