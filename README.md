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

## Windows 开发环境脚本

新 Windows 电脑拉取代码后，优先使用 Docker Desktop 路线，不需要在宿主机直接安装 Python/Node 依赖：

```powershell
.\scripts\setup-env.ps1
.\scripts\start-dev.ps1
```

默认行为：

- `setup-env.ps1` 检查 Docker Compose，并默认使用 Docker Hub 官方 `python`、`node`、`pgvector` 镜像构建开发镜像；
- `start-dev.ps1` 启动 Postgres，执行 Alembic 迁移，初始化 LangGraph checkpointer，再启动 api、worker、scheduler 和 web。

如需使用公司代理或其他镜像源，可通过参数覆盖：

```powershell
.\scripts\setup-env.ps1 -PythonImage <python-image> -NodeImage <node-image> -PgvectorImage <pgvector-image>
```

启动后访问：

- 前端：`http://localhost:5173`
- 后端健康检查：`http://localhost:8000/api/v1/health`
- API 文档：`http://localhost:8000/docs`

如果还需要在宿主机运行后端或前端检查命令，可在已安装 uv 0.11.23、Node.js 22 和 corepack 后同步本机依赖：

```powershell
.\scripts\setup-env.ps1 -LocalDeps -SkipDockerBuild
```

首次需要管理员账号时运行：

```powershell
docker compose -f infra/docker-compose.yml run --rm api uv run python -m app.scripts.create_admin --nickname admin
```
