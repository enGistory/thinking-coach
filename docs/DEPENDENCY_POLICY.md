# Python 依赖与版本锁定规范

版本：v1.0  
基线日期：2026-06-20

## 1. 四层版本约束

1. **解释器系列**：`requires-python = ">=3.12,<3.13"`，防止无审查切换到 Python 3.13/3.14。
2. **解释器补丁版本**：`.python-version` 固定 `3.12.13`，本地、CI 和部署优先使用相同补丁版本。
3. **直接依赖**：`pyproject.toml` 对运行时和开发依赖使用精确版本 `==`。
4. **完整依赖图**：P00 阶段运行 `uv lock` 生成并提交 `uv.lock`，锁定全部传递依赖与文件哈希。

`requirements/direct-pins.txt` 是人工审阅清单，不是第二个可编辑事实源。变更依赖时先修改 `pyproject.toml`，再同步该清单并重新生成 `uv.lock`。

## 2. 工具基线

- Python：3.12.13
- uv：0.11.23
- 依赖清单：`services/backend/pyproject.toml`
- 完整锁文件：`services/backend/uv.lock`（P00 首次联网解析后生成并提交）

本包没有伪造 `uv.lock`。锁文件必须由开发机或 CI 在可访问受信任 Python 包索引的环境中真实解析生成。

## 3. 初始化命令

在 `services/backend` 目录执行：

```powershell
uv --version
uv python install 3.12.13
uv python pin 3.12.13
uv lock
uv sync --all-groups
uv run python scripts/verify_dependency_policy.py
```

首次生成后必须提交：

```text
services/backend/pyproject.toml
services/backend/.python-version
services/backend/uv.lock
```

日常或 CI 不允许重新解析版本，使用：

```powershell
uv lock --check
uv sync --locked --all-groups
```

## 4. 依赖分组

- `[project].dependencies`：生产运行所需依赖。
- `[dependency-groups].dev`：测试、类型检查、Lint 和提交前检查。
- 不把本地模型、GPU 或实验工具放入生产依赖。
- 真实线上模型 smoke test 仍由环境变量 `RUN_LIVE_AI_TESTS=1` 显式开启。


## 4.1 LangGraph 与 LangChain 依赖边界

- 本项目的流程编排只使用 `langgraph` 的 `StateGraph`、`interrupt()`、Checkpoint 和恢复能力。
- `langchain-core==1.4.8` 在 `pyproject.toml` 中显式固定：它是 LangGraph 的基础运行依赖；显式固定便于审计和复现，不表示启用完整 LangChain Agent 框架。
- P0 **不安装完整 `langchain` 包**，也不安装 `langchain-openai`。模型调用由 `openai` / `dashscope` 官方 SDK 和自定义 Provider 完成，结构化结果由 Pydantic 约束。
- P0 不使用 `langchain.agents`、预构建 Agent、LCEL 作为业务主编排，也不允许其绕过 Python 确定性评分、来源核验和防重复规则。
- 只有当后续出现现有 Provider + LangGraph 无法合理解决的明确需求时，才可通过独立 ADR 引入完整 LangChain，并必须补充依赖影响、替代方案、图恢复回归和 Prompt/Schema 回归。
- `uv.lock` 仍负责锁定 `langgraph`、`langchain-core` 及其他传递依赖的完整版本图。

官方依据：

- LangGraph 官方说明可独立使用，不要求安装完整 LangChain：<https://docs.langchain.com/oss/python/langgraph/overview>
- LangGraph 安装文档将 LangChain描述为可选的模型/工具接入方式：<https://docs.langchain.com/oss/python/langgraph/install>
- LangGraph 1.2.6 的包依赖包含 `langchain-core`，而不是完整 `langchain` 元包：<https://pypi.org/project/langgraph/>

## 5. 添加依赖的审批流程

Codex 或人工添加依赖前，必须说明：

1. 当前标准库或已有依赖为何不能完成任务；
2. 引入的包名、用途、许可证和维护状态；
3. 精确目标版本及选择依据；
4. 新增的传递依赖、镜像大小和安全影响；
5. 替代方案；
6. 测试和回滚方式。

获得批准后：

```powershell
uv add "package==x.y.z"
uv lock
uv sync --all-groups
uv run python scripts/verify_dependency_policy.py
uv run ruff check .
uv run mypy app
uv run pytest
```

禁止直接执行无版本的 `pip install package`，禁止在正常功能任务中运行 `uv lock --upgrade` 或批量刷新全部依赖。

## 6. 升级流程

一次升级只处理一个逻辑依赖族，例如：

- FastAPI / Starlette / Pydantic；
- SQLAlchemy / Alembic / PostgreSQL driver；
- LangGraph / langchain-core / Checkpointer；
- OpenAI / DashScope / OSS Provider；
- Pytest / Ruff / Mypy。

升级必须使用独立任务和 ADR，审查 `pyproject.toml` 与 `uv.lock` diff，并运行：

- 全量单元测试；
- 数据库迁移 upgrade / downgrade / upgrade；
- LangGraph interrupt / resume / 重放幂等测试；
- Provider Fake 合约测试；
- Prompt / Schema Golden Case；
- 必要时人工开启真实模型 smoke test。

## 7. 明确禁止的依赖

未经独立任务明确批准，`pyproject.toml` 与 `uv.lock` 不得出现：

```text
torch
tensorflow
transformers
sentence-transformers
faster-whisper
openai-whisper
funasr
modelscope
vllm
llama-cpp-python
onnxruntime-gpu
任何 CUDA / ROCm / 本地模型权重下载器
```

原因：本项目全部 AI 能力使用线上 API，不承担本地模型和 GPU 运行成本。

## 8. Codex 规则

- 不得因为执行普通 Pxx 任务而升级依赖。
- 不得仅为简化几行代码引入新包。
- 不得删除精确版本、改成 `*`、无上界范围或 Git 分支依赖。
- 修改依赖时必须单独列出 `pyproject.toml` 与 `uv.lock` 的变化原因。
- `uv.lock` 出现大量与当前依赖无关的变化时，停止并回退，查明是否误用了全量升级。
- 不读取真实 `.env`，不把包索引凭据写入仓库。

## 9. 版本来源

本基线在 2026-06-20 依据 Python 官方发布页和各项目官方 PyPI 页面核对。版本不是“永久最新”；后续升级应按第 6 节执行，而不是静默追新。
