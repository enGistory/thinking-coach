# Codex CLI 开发编排指南

## 核心原则
Codex 不负责“一次生成整个项目”。把项目拆成 P00-P11 十二个纵向阶段，每次会话只完成一个可以验收的任务；同一任务先计划、再实现、再测试、再 `/review`，由人确认后提交。

## 首次准备
1. 安装并登录 Codex CLI，进入仓库根目录运行 `codex`。
2. 保留仓库内 `.codex/config.toml` 作为本项目配置；不要覆盖 `~/.codex/config.toml`。仅将通用安全默认值放在用户级配置中。
3. 将根 `AGENTS.md` 与三个局部 `AGENTS.md` 放入对应目录。
4. 把 SPEC/SOP 仓库版复制为 `docs/SPEC.md`、`docs/SOP.md`。
5. 只提交 `.env.example`，真实 `.env` 保持在 Git 忽略范围之外。

## 每个任务的标准循环
1. 人工创建分支：`git switch -c feat/Pxx-name`。
2. 启动新的 Codex 会话，不复用上一阶段上下文。
3. 提示 Codex：先读取 AGENTS、SPEC、SOP 和当前任务文件，然后进入 `/plan`。
4. 审核计划：确认文件范围、迁移、接口、测试、风险和 Out of scope。
5. 明确回复“按确认后的计划实现”，让 Codex编码并运行测试。
6. 实现会话结束后新开或切换独立审查上下文，执行 `/review`。
7. Codex 修复 review 中的高/中优先级问题并重新测试。
8. 人工检查 diff，手工执行真实阿里云 smoke test 和手机验收。
9. 人工提交；更新 `docs/progress.md`；下一阶段开启全新会话。

## 会话边界
- `codex resume --last` 只用于同一 Pxx 任务的修复，不能跨任务续聊。
- 默认一个人串行开发；若并行，必须使用独立 `git worktree`，且不能同时修改同一迁移、公共 Schema、同一 Graph 或同一 Provider。
- P00-P06 使用交互式 Codex；`codex exec` 只用于边界稳定的检查、报告或小修复。
- 禁止日常使用 `--yolo`、`danger-full-access` 或跳过审批。

## 单次提示词模板
```text
你现在只执行 Pxx：<任务名>。

Goal
- <本次唯一目标>

Context
- 先读取 AGENTS.md、docs/SPEC.md、docs/SOP.md、docs/tasks/Pxx-*.md。
- 重点目录：<目录>

Constraints
- 不读取或修改 .env / secrets / 生产数据。
- 不实现任务文件 Out of scope 的内容。
- 不新增未批准的生产依赖。
- 所有模型均通过 Provider 调用阿里云线上 API，不加入本地模型。
- 数据库变更必须使用 Alembic；结构化模型输出必须通过 Pydantic。

Done when
- 任务文件中的每条验收条件均有代码或测试证据。
- 运行任务文件指定的 lint、type-check、test、build/migration 命令。
- 使用 /review 审查未提交 diff，并修复高/中优先级问题。

先进入计划阶段，列出受影响文件、迁移/API、测试、风险和不做事项；不要立即编码。
```

## 阶段顺序
P00 工程骨架 → P01 云模型配置 → P02 数据库与账号 → P03 语音纵向切片 → P04 转写与口语指标 → P05 LangGraph 会话 → P06 严格评审 → P07 缺陷经验库 → P08 来源与出题 → P09 永不重复 → P10 随机突击 → P11 报告、隐私、部署与发布验收。

## Python 依赖任务的额外规则

- P00 先读取 `docs/DEPENDENCY_POLICY.md`、`services/backend/pyproject.toml` 和 `services/backend/DEPENDENCIES.md`。
- 首次由 Codex 运行 `uv lock` 前，必须先报告目标 Python/uv 版本、依赖数量和预计新增文件。
- Codex 不得在普通 Pxx 功能任务中执行 `uv lock --upgrade`、`uv add` 或修改版本号。
- 新增依赖必须单独建立任务，先说明现有依赖为何不够，再获得人工批准。
- LangGraph 采用 standalone 模式；`langchain-core` 已固定，完整 `langchain` / `langchain-openai` 未经 ADR 不得加入。
- 锁文件 diff 只允许包含本次批准的依赖及其必要传递依赖；出现大面积无关变化时停止。
- 验收命令：`uv lock --check`、`uv sync --locked --all-groups`、`uv run python scripts/verify_dependency_policy.py`。

