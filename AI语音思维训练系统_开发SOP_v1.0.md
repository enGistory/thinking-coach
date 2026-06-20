**开发、测试、部署与运营标准作业程序（SOP）**

| **文档版本** | v1.0                                   |
|--------------|----------------------------------------|
| **编制日期** | 2026-06-20                             |
| **适用对象** | 个人开发；最多 3-4 名用户              |
| **文档状态** | 初始开发基线 / 尚未开始开发              |

**核心定位：证据驱动、语音突击、缺陷自适应、题目永不重复**

# 文档目的

本 SOP 用于把 SPEC 转换为可执行开发步骤。所有阶段采用“可运行纵向切片 → 质量校准 → 扩展功能”的顺序，禁止先建设复杂基础设施或自由 Agent。每个阶段只有通过验收门槛后才能进入下一阶段。

| **最重要的开发纪律：**先验证语音答辩和评审闭环，再建设自动出题；固定测试题只允许用于开发集成，不得作为正式日常训练题。 |
|------------------------------------------------------------------------------------------------------------------------|

# 目录

- 1\. 冻结技术栈与资源

- 2\. 仓库与工程结构

- 3\. 本地环境初始化

- 4\. 配置和数据库初始化

- 5\. 分阶段开发 SOP

- 6\. LangGraph 开发 SOP

- 7\. AI Prompt 与结构化输出 SOP

- 8\. 来源采集与题目生成 SOP

- 9\. 防重复 SOP

- 10\. 评审校准 SOP

- 11\. 测试 SOP

- 12\. 部署 SOP

- 13\. 日常运行与维护 SOP

- 14\. 故障处理 SOP

- 15\. 发布检查单

- 16\. Definition of Done

# 1. 冻结技术栈与资源

## 1.1 P0 技术栈

| **类别**  | **固定选择**                                                             | **备注**                                                  |
|-----------|--------------------------------------------------------------------------|-----------------------------------------------------------|
| 前端      | Vue 3 + TypeScript + Vite + Pinia + Vue Router + vite-plugin-pwa         | 手机浏览器安装到桌面。                                    |
| 后端      | Python 3.12 + FastAPI + Pydantic v2                                      | 先用 REST + 轮询，暂不做复杂实时协议。                    |
| 数据库    | PostgreSQL 16 + pgvector                                                 | 单实例。                                                  |
| ORM       | SQLAlchemy 2 + Alembic + asyncpg                                         | 所有表由迁移管理。                                        |
| AI编排    | LangGraph StateGraph + Postgres Checkpointer                             | 只做固定 Workflow。                                       |
| 任务      | 数据库 ai_job 表 + 独立 worker 进程                                      | P0 不引入 Celery/Redis/RabbitMQ。                         |
| 调度      | APScheduler 独立 scheduler 进程                                          | 随机突击、库存、清理、周报。                              |
| 语音      | MediaRecorder + AliyunFunASRProvider（fun-asr）+ AliyunCosyVoiceProvider | 仅调用云端模型；保留时间戳；服务器不安装语音模型。        |
| LLM       | AliyunQwenProvider + OpenAI Python SDK + Pydantic 结构化输出             | qwen3.5-plus / qwen3.6-plus；模型和密钥只在环境变量配置。 |
| 存储      | 服务器私有目录 /data/thinking-app/audio                                  | P0 不上 MinIO。                                           |
| 部署      | Docker Compose + Nginx + HTTPS                                           | 普通 CPU 服务器即可；不采购 GPU，不下载模型权重。         |
| Embedding | AliyunEmbeddingProvider（text-embedding-v4）                             | 用于题目语义查重与历史缺陷候选召回。                      |

## 1.2 开发资源清单

| **资源**                          | **必要性**       | **验收**                                                           |
|-----------------------------------|------------------|--------------------------------------------------------------------|
| Windows 开发电脑                  | 必须             | 可运行 Docker Desktop、Node、Python、Git。                         |
| Android 或 iPhone 实机            | 必须             | 可测试麦克风、PWA 安装和通知。                                     |
| 公网 Linux 服务器                 | 联调后需要       | 具备域名、HTTPS、Docker Compose。                                  |
| 域名与证书                        | 推送阶段需要     | 浏览器显示有效 HTTPS。                                             |
| 阿里云百炼 API Key                | 必须             | DASHSCOPE_API_KEY、Workspace Base URL 和四类模型 smoke test 通过。 |
| Search API 或 Web Search Provider | 自动出题阶段需要 | 可返回可访问来源 URL。                                             |
| STT 能力                          | 必须             | fun-asr 对真实中文录音返回可定位时间戳。                           |
| 3-4 个测试账号                    | 验收阶段需要     | 用户数据互相隔离。                                                 |
| GPU / 本地模型                    | 不需要           | 不得安装本地 LLM、ASR、TTS、Embedding 权重。                       |

## 1.3 P0 禁止引入

- Kubernetes、Nacos、Kafka、RabbitMQ、微服务、独立向量数据库。

- 自由多 Agent、模型自动修改评分规则、动态生成数据库结构。

- 后台录音、情绪识别、声纹识别、实时全双工语音。

- 应用商店发布、支付、排行榜、团队管理和复杂管理员权限。

# 2. 仓库与工程结构

## 2.1 Monorepo

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>thinking-coach/<br />
├── apps/<br />
│ └── web/ # Vue3 PWA<br />
├── services/<br />
│ └── backend/<br />
│ ├── app/<br />
│ │ ├── api/v1/<br />
│ │ ├── core/<br />
│ │ ├── db/<br />
│ │ ├── models/<br />
│ │ ├── schemas/<br />
│ │ ├── repositories/<br />
│ │ ├── domain/ # 确定性规则<br />
│ │ ├── ai/ # Provider / Prompt / Schema<br />
│ │ ├── graphs/ # LangGraph<br />
│ │ ├── workers/<br />
│ │ ├── scheduler/<br />
│ │ └── main.py<br />
│ ├── prompts/<br />
│ ├── tests/<br />
│ ├── alembic/<br />
│ └── pyproject.toml<br />
├── infra/<br />
│ ├── docker-compose.yml<br />
│ ├── nginx/<br />
│ └── postgres/init/<br />
├── docs/<br />
│ ├── SPEC.md<br />
│ ├── SOP.md<br />
│ ├── ADR/<br />
│ └── api-examples/<br />
├── .env.example<br />
├── Makefile<br />
└── README.md</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 2.2 分层规则

| **目录**          | **允许包含**                                       | **禁止**                                 |
|-------------------|----------------------------------------------------|------------------------------------------|
| api               | HTTP 参数、鉴权、调用应用服务、响应转换。          | 直接写 Prompt、SQL 或评分规则。          |
| domain            | 缺陷优先级、评分封顶、来源门槛、查重阈值、状态机。 | 依赖 FastAPI、LangGraph 或具体模型 SDK。 |
| ai                | Provider、Pydantic 输出、Prompt 加载、模型适配。   | 直接写业务表。                           |
| graphs            | 节点、边、条件路由、interrupt、状态。              | 重复实现 domain 规则。                   |
| repositories      | 数据库读写和事务。                                 | 模型语义判断。                           |
| workers/scheduler | 任务领取、锁、重试、定时触发。                     | 长期业务状态仅放内存。                   |

## 2.3 分支与提交

- 主分支：main；开发分支：dev；功能分支：feature/\<scope\>；修复：fix/\<scope\>。

- 提交格式：feat / fix / refactor / test / docs / chore。

- 一个提交只解决一个明确问题；Prompt 变更必须与回归结果一起提交。

- 所有数据库结构变化只通过 Alembic 迁移。

- 任何改动不得绕过 CI 的单元测试、类型检查和 Prompt 回归。

# 3. 本地环境初始化

## 3.1 基础工具

- Git；Docker Desktop；Python 3.12；Node.js 22；pnpm；可选 VS Code 或 PyCharm。

- Windows 上统一使用 PowerShell；脚本文件保存为 UTF-8、LF，避免 WSL/CRLF 问题。

- Python 依赖必须有锁文件；Node 依赖必须提交 pnpm-lock.yaml。

## 3.2 初始化仓库

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>mkdir thinking-coach<br />
cd thinking-coach<br />
git init<br />
mkdir apps services infra docs<br />
<br />
# 前端<br />
pnpm create vite apps/web --template vue-ts<br />
cd apps/web<br />
pnpm install<br />
pnpm add vue-router pinia<br />
pnpm add -D vite-plugin-pwa<br />
cd ../..<br />
<br />
# 后端（依赖已由 pyproject.toml 精确固定，禁止在此散装 uv add）<br />
cd services/backend<br />
uv --version                         # 要求 0.11.23<br />
uv python install 3.12.13<br />
uv python pin 3.12.13<br />
uv lock                              # 首次联网解析并生成 uv.lock<br />
uv sync --all-groups<br />
uv run python scripts/verify_dependency_policy.py<br />
# 关键边界：显式安装 langchain-core==1.4.8；不安装完整 langchain / langchain-openai<br />
cd ../..</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

| **版本管理：**不要把文档中的版本号理解为“永远最新”。首次安装后锁定实际可用版本；升级依赖必须单独建立 ADR、运行回归并确认 LangGraph interrupt/checkpointer 行为未变化。 |
|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

## 3.3 前端 PWA 基础

> **1.** 配置 manifest：name、short_name、icons、display=standalone、start_url。
>
> **2.** 注册 Service Worker；实现离线兜底页。
>
> **3.** 封装 AudioRecorder，检测支持的 mimeType，优先 audio/webm;codecs=opus。
>
> **4.** 封装 Notification 与 PushSubscription；权限只在用户明确操作后申请。
>
> **5.** 实现应用安装提示和 iOS“添加到主屏幕”说明。

# 4. 配置和数据库初始化

## 4.1 .env.example

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>APP_ENV=dev<br />
APP_BASE_URL=http://localhost:8000<br />
WEB_BASE_URL=http://localhost:5173<br />
DATABASE_URL=postgresql+asyncpg://thinking:thinking@postgres:5432/thinking<br />
DATABASE_SYNC_URL=postgresql://thinking:thinking@postgres:5432/thinking<br />
JWT_SECRET=CHANGE_ME<br />
JWT_ACCESS_MINUTES=30<br />
AUDIO_ROOT=/data/audio<br />
AUDIO_RETENTION_DAYS=30<br />
<br />
# AI：正式环境仅使用阿里云线上模型<br />
AI_PROVIDER=aliyun<br />
AI_PROVIDER_MODE=aliyun<br />
DASHSCOPE_API_KEY=<br />
DASHSCOPE_BASE_URL=https://&lt;WorkspaceId&gt;.cn-beijing.maas.aliyuncs.com/compatible-mode/v1<br />
<br />
QWEN_DIALOG_MODEL=qwen3.6-plus<br />
QWEN_QUESTION_MODEL=qwen3.5-plus<br />
QWEN_REVIEW_MODEL=qwen3.6-plus<br />
QWEN_VERIFY_MODEL=qwen3.6-plus<br />
QWEN_FALLBACK_MODEL=qwen3.5-plus<br />
<br />
ALIYUN_ASR_MODEL=fun-asr<br />
ALIYUN_TTS_MODEL=cosyvoice-v3.5-plus<br />
ALIYUN_EMBEDDING_MODEL=text-embedding-v4<br />
<br />
LLM_TIMEOUT_SECONDS=120<br />
LLM_MAX_RETRIES=2<br />
LLM_TEMPERATURE_DIALOG=0.2<br />
LLM_TEMPERATURE_QUESTION=0.7<br />
LLM_TEMPERATURE_REVIEW=0.0<br />
QWEN_ENABLE_THINKING_QUESTION=true<br />
QWEN_ENABLE_THINKING_REVIEW=true<br />
QWEN_ENABLE_THINKING_DIALOG=false<br />
<br />
# 可选：私有 OSS 临时签名 URL<br />
ALIYUN_OSS_ENDPOINT=<br />
ALIYUN_OSS_BUCKET=<br />
ALIYUN_OSS_ACCESS_KEY_ID=<br />
ALIYUN_OSS_ACCESS_KEY_SECRET=<br />
ALIYUN_OSS_SIGNED_URL_TTL_SECONDS=900<br />
<br />
SEARCH_PROVIDER=web_search<br />
WEB_PUSH_VAPID_PUBLIC_KEY=<br />
WEB_PUSH_VAPID_PRIVATE_KEY=<br />
LANGGRAPH_AES_KEY=<br />
TZ=America/New_York</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 4.2 数据库初始化 SOP

> **1.** 启动 PostgreSQL 容器并确认数据库可连接。
>
> **2.** 执行 CREATE EXTENSION IF NOT EXISTS vector。
>
> **3.** 配置 Alembic 使用同步 DATABASE_SYNC_URL。
>
> **4.** 建立第一批表：app_user、user_training_policy、training_session、voice_attempt、ai_job。
>
> **5.** 后续每个阶段按需求增加表，不允许一次性创建未验证的完整大模型。
>
> **6.** 安装 LangGraph Postgres checkpointer 后执行其 setup；不得手工修改其内部表。
>
> **7.** 生成一个管理员和一个测试用户；密码不得明文存储。

## 4.3 Docker Compose 开发环境

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>services:<br />
postgres:<br />
image: pgvector/pgvector:pg16<br />
environment:<br />
POSTGRES_DB: thinking<br />
POSTGRES_USER: thinking<br />
POSTGRES_PASSWORD: thinking<br />
volumes:<br />
- ./data/postgres:/var/lib/postgresql/data<br />
<br />
api:<br />
build: ./services/backend<br />
command: uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload<br />
env_file: .env<br />
volumes:<br />
- ./services/backend:/app<br />
- ./data/audio:/data/audio<br />
depends_on: [postgres]<br />
<br />
worker:<br />
build: ./services/backend<br />
command: uv run python -m app.workers.main<br />
env_file: .env<br />
volumes:<br />
- ./data/audio:/data/audio<br />
depends_on: [postgres]<br />
<br />
scheduler:<br />
build: ./services/backend<br />
command: uv run python -m app.scheduler.main<br />
env_file: .env<br />
depends_on: [postgres]</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

# 5. 分阶段开发 SOP

| **阶段**                   | **主要工作**                                                                               | **退出条件**                                                                 |
|----------------------------|--------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| 阶段 0：工程骨架与规范     | 建立仓库、Codex 指令、CI、配置、健康检查、日志、错误码、ADR。                              | Codex 能正确读取 AGENTS.md；API /health 可用；前端可访问；CI 通过。          |
| 阶段 1：账号和训练边界     | 邀请码、登录、USER/ADMIN、时间窗口、音频保留、数据隔离。                                   | 两个账号无法读取彼此数据。                                                   |
| 阶段 2：语音纵向切片       | PWA 录音、上传、回放、音频元数据、原始文件存储。                                           | 真机连续录制 10 次无丢失；上传失败可重试。                                   |
| 阶段 3：STT 与口语指标     | AliyunFunASRProvider、时间戳、原始稿/校正版、停顿和口头禅统计；完成四类云模型 smoke test。 | 真实中文录音可定位音频片段；Qwen、ASR、TTS、Embedding 均能通过环境变量调用。 |
| 阶段 4：LangGraph 答辩闭环 | 固定开发测试题；第一答 interrupt、追问、最终答、恢复。                                     | 退出页面后能用同一 thread 恢复。                                             |
| 阶段 5：严格评审           | 冻结 Rubric、结构提取、初评、证据复核、硬封顶、三类评分。                                  | 所有负面评价都能点到原话时间点。                                             |
| 阶段 6：缺陷经验库         | defect_definition、occurrence、profile、优先级、历史相似问题。                             | 同一问题跨题目累计，单次不直接确认稳定缺陷。                                 |
| 阶段 7：来源与自动出题     | Search/Fetch、来源等级、Claim、候选题、Rubric、来源公开。                                  | 题目事实支持率 100%；无来源不投放。                                          |
| 阶段 8：防重复             | 哈希、embedding、指纹、LLM终审、模板家族禁用。                                             | 构造的换皮题全部被拦截。                                                     |
| 阶段 9：随机突击与推送     | 题目库存、随机窗口、Web Push、接受/过期/曝光退役。                                         | 用户不能预知类型；未接受不扣分。                                             |
| 阶段 10：报告与申诉        | 本次报告、周报告、转写纠错、重复/来源/评审申诉。                                           | 申诉可暂停缺陷确认并记录处理结果。                                           |
| 阶段 11：安全、备份与部署  | HTTPS、私有音频、备份、删除、监控、恢复演练。                                              | 完成端到端生产验收。                                                         |

## 5.1 阶段 0：工程骨架

> **1.** 创建 FastAPI app、统一响应、错误码、request_id 中间件和结构化日志。
>
> **2.** 配置 Ruff、Mypy、Pytest；前端配置 ESLint/TypeScript 检查。
>
> **3.** 建立 GitHub Actions 或本地 CI：backend test + type check + frontend build。
>
> **4.** 创建 ADR-001：选择 PWA；ADR-002：选择 LangGraph；ADR-003：选择数据库任务队列。
>
> **5.** 建立 /health，分别检测 app、database、audio_root 可写。

## 5.2 阶段 1：账号和隔离

> **1.** 完成 app_user、invitation、refresh_token（可选）和 user_training_policy 迁移。
>
> **2.** 实现密码哈希、JWT、当前用户依赖。
>
> **3.** 所有 repository 方法必须显式接收 user_id；写跨用户越权测试。
>
> **4.** 管理员后台只返回任务状态和用户状态，不返回语音正文。

## 5.3 阶段 2：录音与上传

> **1.** 前端检测 getUserMedia 与 MediaRecorder；申请权限前展示用途。
>
> **2.** 录音开始后隐藏实时转写；保存 blob、时长、mimeType。
>
> **3.** 先创建 voice_attempt，再通过 PUT 上传音频，使用幂等键。
>
> **4.** 服务端校验 MIME、大小、时长和 user/session 归属；文件名使用 UUID。
>
> **5.** 上传失败保留本地 blob，允许重试；服务器返回 checksum。
>
> **6.** 完成回放和删除接口。

## 5.4 阶段 3：STT

> **1.** 定义 STTProvider 抽象与 Transcript、Segment、Word Pydantic 模型。
>
> 2\. 实现 AliyunFunASRProvider；录音上传后调用 fun-asr，解析词级或片段级时间戳。
>
> **3.** 将 segment 和 word 时间戳写入 transcript_segment。
>
> **4.** 建立中文专业词纠错表，但不得自动改写整句话。
>
> **5.** 实现 transcript correction API，只保存差异和纠错原因。
>
> **6.** 计算音频长度、有效说话时长、长停顿、口头禅、语速和超时。

## 5.5 阶段 4：LangGraph 训练闭环

> **1.** 先使用一条手工核验的开发测试题和固定 Rubric，禁止投入正式题库。
>
> **2.** 创建 TrainingState、StateGraph、Postgres Checkpointer。
>
> **3.** 实现 wait_first_audio interrupt；API 接收 attempt_id 后通过 Command(resume=...) 恢复。
>
> **4.** 实现动态追问节点，P0 固定 1 轮；稳定后扩展到最多 2 轮。
>
> **5.** 实现 wait_final_audio 和 final state。
>
> **6.** 浏览器刷新、API 重启、worker 重启后分别验证恢复。
>
> **7.** 检查所有 interrupt 前副作用是否幂等。

## 5.6 阶段 5：评审

> **1.** 定义 AnswerStructure、LogicReview、LogicIssue、EvidenceVerification。
>
> **2.** 冻结 Rubric 后才开放题目；写数据库时间戳和 hash。
>
> **3.** 把结构提取、逻辑初评、口语统计、应变评审拆成独立节点。
>
> **4.** Evidence Verifier 必须校验 quote 存在于校正版转写，并映射原始 segment。
>
> **5.** Python domain/scoring.py 计算权重和封顶；模型只返回判定，不直接给最终总分。
>
> **6.** 报告中每条问题必须可点击播放对应时间段。

## 5.7 阶段 6：缺陷经验库

> **1.** 初始化 defect_definition 字典和判断标准。
>
> **2.** 将 verified issue 转为 defect_occurrence；低置信度默认 pending。
>
> **3.** 实现 profile 更新规则：次数、跨场景、纠正后复发、严重度、置信度。
>
> **4.** 实现近似历史问题召回：编码精确匹配 → embedding → LLM 根因终审。
>
> **5.** 展示“本次与历史相似在哪里”，不得只显示相似度数字。

## 5.8 阶段 7：来源与自动出题

> **1.** 实现 SearchProvider、ContentFetcher 和文档解析器。
>
> **2.** 保存来源 title、publisher、URL、published_at、accessed_at、level、snapshot_hash。
>
> **3.** 使用结构化输出提取 Claim；再用独立验证节点检查 Claim 与证据。
>
> **4.** 仅使用 VERIFIED Claim 生成 8-12 个 QuestionCandidate。
>
> **5.** 对每道候选题做逐句 claim mapping；任何 unsupported fact 直接淘汰。
>
> **6.** 生成隐藏 Rubric 和题目指纹；冻结后进入 READY。
>
> **7.** 完成训练后才公开来源和加工说明。

## 5.9 阶段 8：防重复

> **1.** 建立文本规范化器：数字、人名、公司、角色同义词。
>
> **2.** 计算 normalized_hash；命中直接淘汰。
>
> **3.** 生成 prompt、决策对象和摘要 embedding，使用 pgvector 精确检索。
>
> **4.** 比较结构指纹；同缺陷复测至少变化 4 个维度。
>
> **5.** 把最相似历史题交给 LLM 终审；保存判断理由。
>
> **6.** 建立“明显换皮”用户反馈路径，题目和模板家族永久禁用。

## 5.10 阶段 9：随机突击

> **1.** Scheduler 每日生成每用户候选决策点，不固定同一时间。
>
> **2.** 根据缺陷优先级和题目库存选择题目，并保存 delivery_decision。
>
> **3.** 发送 Web Push，仅显示突击到达，不显示题型。
>
> **4.** 用户接受后锁定 session；曝光题目后，question.exposed_count=1 并永久退役。
>
> **5.** 未接受、过期、已曝光退出分别使用不同状态，不混入能力评分。

## 5.11 阶段 10-11：报告、申诉和部署

> **1.** 生成本次报告、周报告和缺陷趋势；不展示人格化结论。
>
> **2.** 实现 4 类申诉：转写、重复、来源、评审。
>
> **3.** 建立数据删除、导出、音频清理和审计日志。
>
> **4.** 完成 Docker Compose、Nginx、HTTPS、数据库备份和恢复演练。
>
> **5.** 在 3-4 个真实账号上完成不少于 30 次端到端测试后再长期使用。

# 6. LangGraph 开发 SOP

## 6.1 图设计步骤

> **1.** 先画业务状态机，再定义 State；不得从“Agent 可以做什么”开始。
>
> **2.** 只把需要独立重试、分支、耗时调用、checkpoint 或 interrupt 的步骤设计为节点。
>
> **3.** 每个节点明确：输入字段、输出字段、外部副作用、幂等键、错误码、重试次数。
>
> **4.** 条件路由只能读取结构化状态，不能根据自由文本隐式跳转。
>
> **5.** 图完成后写一张节点表和一张状态转换测试表。

## 6.2 interrupt 实现规则

- 编译图时必须传入持久化 checkpointer。

- thread_id 必须使用稳定业务 ID，不使用随机临时值。

- interrupt payload 必须 JSON 可序列化，不传数据库连接、文件句柄或模型对象。

- 节点恢复会重新执行 interrupt 前代码，因此前置副作用必须幂等。

- 推荐把“创建 attempt / 发通知 / 写状态”拆到 interrupt 之前的独立节点。

- Graph State 与业务数据库不互相替代；完成节点必须将业务结果显式落库。

## 6.3 图节点模板

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>async def transcribe_first(state: TrainingState, deps: Deps) -&gt; dict:<br />
attempt = await deps.attempt_repo.get_owned(<br />
attempt_id=state["first_attempt_id"],<br />
user_id=state["user_id"],<br />
)<br />
transcript = await deps.stt.transcribe(attempt.audio_path)<br />
await deps.transcript_repo.upsert(attempt.id, transcript)<br />
return {<br />
"current_stage": "FIRST_TRANSCRIBED",<br />
"first_transcript_id": transcript.id,<br />
}</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

| **节点准则：**节点可以重放；写入必须 upsert 或受唯一约束保护；不得依赖进程内全局变量保存会话。 |
|------------------------------------------------------------------------------------------------|

## 6.4 图测试矩阵

| **场景**                         | **预期**                                          |
|----------------------------------|---------------------------------------------------|
| 正常第一答 → 追问 → 最终答       | COMPLETED，三段 attempt 均可追溯。                |
| interrupt 后 API 重启            | 同 thread_id 恢复。                               |
| worker 在 LLM 调用后、写库前崩溃 | 重试不产生重复 issue。                            |
| 同一 resume 请求重复提交         | 幂等，仅一个 job 和一个状态推进。                 |
| STT 连续失败                     | INVALID 或 FAILED_RETRYABLE，不生成评分。         |
| 来源被撤销                       | 尚未曝光的 session 取消；已完成报告保留历史说明。 |
| 用户曝光题目后退出               | ABANDONED，题目永久退役。                         |

# 7. AI Prompt 与结构化输出 SOP

## 7.1 每个 AI 任务单独建 Prompt

| **任务**               | **输入**                               | **输出**                                |
|------------------------|----------------------------------------|-----------------------------------------|
| claim_extraction       | 来源正文与元数据                       | Claim\[\]。                             |
| claim_verification     | Claim + 证据片段                       | 支持状态与修正。                        |
| question_generation    | 缺陷目标 + VERIFIED Claim              | QuestionCandidate\[\]。                 |
| duplicate_adjudication | 候选题 + 相似历史题                    | NEW / TRANSFER / REPHRASE / DUPLICATE。 |
| answer_structure       | 题目 + 逐字稿                          | AnswerStructure。                       |
| logic_review           | 冻结 Rubric + AnswerStructure + 逐字稿 | LogicReview。                           |
| followup_generation    | 最大缺口 + 历史追问                    | 单个追问。                              |
| evidence_verification  | LogicIssue + 逐字稿和时间戳            | EvidenceVerification。                  |
| historical_match       | 本次 issue + 历史 occurrence           | 根因匹配。                              |
| report_narrative       | 已验证结构化结果                       | 用户可读总结，不得新增判断。            |

## 7.2 Prompt 文件规范

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>prompts/logic_review/<br />
├── v1.0.0.system.md<br />
├── v1.0.0.user.md<br />
├── v1.0.0.schema.json<br />
├── CHANGELOG.md<br />
└── golden_cases/</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

- Prompt 中明确角色、禁止事项、评分依据和输出 Schema。

- 必须要求“未表达”与“明确错误”分开。

- 不得要求输出隐藏思维链；只输出可验证结论和证据。

- 模型温度、最大输出、provider 和 model 均记录在 model_run。

- Prompt 更新先跑 Golden Set；关键指标下降则不得上线。

## 7.3 结构化输出错误处理

> **1.** SDK 先启用 JSON Schema/Structured Output。
>
> **2.** Pydantic 校验失败时，保存原响应和错误摘要，不记录敏感全文日志。
>
> **3.** 同模型以“只修复结构，不改变语义”重试 1 次。
>
> **4.** 仍失败则使用备用模型或将 job 标记 FAILED_RETRYABLE。
>
> **5.** 任何未经 Schema 校验的数据不得写入正式报告和缺陷画像。

# 8. 来源采集与题目生成 SOP

## 8.1 来源采集

> **1.** 读取本次目标缺陷和未覆盖场景，生成 3-5 个检索方向。
>
> **2.** 优先使用 S/A 级来源；B 级关键事实必须交叉验证。
>
> **3.** 抓取完整正文或 PDF，不以搜索摘要作为证据。
>
> **4.** 记录标题、发布者、时间、访问时间、URL、内容类型和快照哈希。
>
> **5.** 网页正文提取失败则换来源；PDF 解析需保留页码。
>
> **6.** 对时效性内容设置 valid_until；过期后不得继续投放。

## 8.2 Claim 提取与验证

> **1.** 一个 Claim 只包含一个可核验命题。
>
> **2.** Claim 必须映射 evidence_locator 和短证据片段。
>
> **3.** 独立 verifier 判断 VERIFIED / CONFLICTED / UNSUPPORTED。
>
> **4.** CONFLICTED 可用于“材料冲突分析题”，但题目必须明确冲突；不得擅自选边。
>
> **5.** UNSUPPORTED Claim 永久禁止进入候选题。

## 8.3 候选题生成与冻结

> **1.** 一次生成 8-12 道候选题，而非只生成 1 道。
>
> **2.** 每道题输出 claim_ids、target_defects、fingerprint、expected_reasoning、prohibited_inferences。
>
> **3.** 题目事实逐句映射 Claim；缺少映射的句子删除或整题淘汰。
>
> **4.** 运行四级查重并选择“诊断价值高、历史距离远”的题。
>
> **5.** 生成隐藏 Rubric；Rubric 必须在 question.exposed_at 之前冻结。
>
> **6.** 题目状态从 DRAFT → VERIFIED → DEDUPED → READY。

## 8.4 来源公开

- 答题前只显示来源已核验、数量、最高等级和来源凭证编号。

- 最终回答后展示完整来源列表、事实映射、匿名化和新增假设说明。

- 来源失效但已有合法证据快照时，标记“原链接失效”；没有快照则停止后续投放。

# 9. 防重复 SOP

## 9.1 查重执行顺序

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>normalize(candidate) → exact hash<br />
↓ 未命中<br />
embedding search：prompt / decision / summary<br />
↓ 低于直接拒绝阈值<br />
structural comparison：至少 4-6 个维度变化<br />
↓<br />
LLM adjudication with top 5-10 historical questions<br />
↓<br />
PASS 才能进入 READY</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 9.2 初始阈值与校准

| **规则**   | **初始值**                         | **说明**                     |
|------------|------------------------------------|------------------------------|
| 完全重复   | normalized_hash 命中               | 直接拒绝。                   |
| 高语义相似 | cosine \>= 0.92                    | 直接拒绝。                   |
| 灰区       | 0.82 \<= cosine \< 0.92            | 必须 LLM 终审。              |
| 结构变化   | 普通复测 \>=4 维；高频缺陷 \>=6 维 | 人名、数字、公司名不计变化。 |
| 同事件     | source_event_id 不可复用           | 默认永久。                   |
| 同题型连续 | 不得连续 3 次                      | 防止形成固定套路。           |

| **阈值不是常数真理：**用人工标注的重复/非重复样本校准阈值；任何阈值变更都必须跑防重复回归集。 |
|-----------------------------------------------------------------------------------------------|

## 9.3 用户重复投诉处理

> **1.** 立即将当前题标记 INVALID，不计分。
>
> **2.** 保存用户认为相似的历史题 ID。
>
> **3.** 人工或独立模型判断是文本、场景、结构还是答案骨架重复。
>
> **4.** 将模板家族加入 denylist；重新计算相关历史候选题。
>
> **5.** 补发全新题，但不要求用户当天必须再答。

# 10. 评审校准 SOP

## 10.1 Golden Set

建立至少 50 个手工标注回答作为初始 Golden Set，覆盖正确、边界和明显错误。每个样本包含题目、Rubric、逐字稿、期望问题编码、证据片段、封顶规则和允许的分数区间。

| **样本类型**           | **最低覆盖** |
|------------------------|--------------|
| 答非所问但表达流畅     | 5            |
| 结论明确但证据不足     | 5            |
| 框架空泛               | 5            |
| 合理承认未知           | 5            |
| 不同结论但逻辑充分     | 5            |
| 管理题进入流程细节     | 5            |
| 追问后有效修正         | 5            |
| 转写错误干扰           | 5            |
| 时间戳证据边界         | 5            |
| 无明显缺陷的高质量回答 | 5            |

## 10.2 每次评审变更流程

> **1.** 提出变更原因：误判、漏判、漂移、证据错误或用户申诉。
>
> **2.** 新增对应 Golden Case，先复现问题。
>
> **3.** 修改 Prompt、Schema 或 Python 规则；不得同时无差别修改多个层。
>
> **4.** 运行回归：问题识别准确率、证据命中率、结构化输出成功率、分数稳定性。
>
> **5.** 关键指标不下降后发布新 prompt_version。
>
> **6.** 观察真实 10 次训练；异常则回滚。

## 10.3 评分稳定性验收

- 同一输入重复执行 5 次，问题编码核心集合应高度一致。

- 同一答案的总分波动目标不超过 5 分；超出时重点检查模型随机性和 Rubric。

- Evidence Verifier 对不存在的 quote 必须拒绝。

- 逻辑问题与口语问题不得互相替代。

- 模型不得因为用户选择与案例真实决策不同而自动扣分。

# 11. 测试 SOP

## 11.1 测试层级

| **层级**          | **范围**                                                         |
|-------------------|------------------------------------------------------------------|
| 单元测试          | 优先级公式、封顶规则、状态转换、文本规范化、权限过滤、音频保留。 |
| Provider 合约测试 | LLM/STT/Search/Embedding 的输入输出和错误映射。                  |
| 图测试            | 节点、路由、interrupt、resume、checkpoint、幂等。                |
| 集成测试          | FastAPI + PostgreSQL + Worker + 文件存储。                       |
| Prompt 回归       | Golden Set。                                                     |
| E2E               | 真机通知、播放、录音、上传、追问、报告、来源、删除。             |
| 恢复测试          | API/worker/数据库短暂故障后的状态恢复。                          |
| 隐私测试          | 越权、日志敏感信息、删除完整性。                                 |

## 11.2 每次合并前检查

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th># backend<br />
uv run ruff check .<br />
uv run mypy app<br />
uv run pytest -q<br />
<br />
# frontend<br />
pnpm lint<br />
pnpm type-check<br />
pnpm build<br />
<br />
# migrations<br />
alembic upgrade head<br />
alembic downgrade -1<br />
alembic upgrade head</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 11.3 E2E 必测场景

- 通知授权拒绝后应用仍可手动查看待处理突击。

- 麦克风拒绝、录音中断、网络断开、上传重试。

- 题目播放后关闭页面，该题被永久退役。

- 第一答提交后刷新页面，能继续追问。

- STT 转写错误被纠正后，评审基于校正版且保留原稿。

- 用户标记重复，分数撤销，模板家族禁用。

- 来源错误申诉后，该题状态暂停。

- 删除训练记录后，音频和相关向量一并删除。

- 两个用户互相无法访问 training、audio、report、defect。

# 12. 部署 SOP

## 12.1 服务器目录

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>/data/thinking-app/<br />
├── compose/<br />
├── postgres/<br />
├── audio/<br />
│ └── &lt;user_id&gt;/&lt;yyyy-mm&gt;/<br />
├── backup/<br />
├── logs/<br />
└── nginx/</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 12.2 首次部署

> **1.** 准备域名 A 记录和防火墙端口 80/443。
>
> **2.** 复制 .env.production，生成强 JWT_SECRET、VAPID 密钥和 LANGGRAPH_AES_KEY。
>
> **3.** 构建前端和后端镜像；启动 postgres。
>
> **4.** 执行 Alembic migration 和 pgvector extension。
>
> **5.** 执行 LangGraph checkpointer setup。
>
> **6.** 启动 api、worker、scheduler、web、nginx。
>
> **7.** 申请并配置 HTTPS；HTTP 强制跳转 HTTPS。
>
> **8.** 创建管理员邀请码和测试用户。
>
> **9.** 完成 /health、录音、STT、图恢复、推送、删除和备份验收。

## 12.3 发布命令参考

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>git pull<br />
docker compose build api worker scheduler web<br />
docker compose up -d postgres<br />
docker compose run --rm api alembic upgrade head<br />
docker compose run --rm api python -m app.scripts.setup_langgraph<br />
docker compose up -d<br />
docker compose ps<br />
curl -fsS https://your-domain.example/api/v1/health</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 12.4 回滚

> **1.** 发布前记录当前镜像 tag 和数据库 migration revision。
>
> **2.** 代码回滚优先使用上一镜像；数据库迁移只有明确可逆时才 downgrade。
>
> **3.** Prompt 回滚只切换 active version，不删除历史版本。
>
> **4.** 模型供应商异常时切备用 Provider；不得临时放宽来源或证据门槛。

# 13. 日常运行与维护 SOP

| **频率**   | **操作**                                                            |
|------------|---------------------------------------------------------------------|
| 每 1 分钟  | worker 领取 ai_job；scheduler 检查到期突击。                        |
| 每天       | 补充 READY 题目库存；清理过期通知；备份数据库；清理到期音频。       |
| 每周       | 生成周报告；重算 defect_profile；检查重复投诉、来源失效和评审申诉。 |
| 每月       | 恢复备份演练；评估 Prompt 漂移；检查 API 成本和音频容量。           |
| 依赖升级前 | 阅读官方变更，建立 ADR，跑完整回归和图恢复测试。                    |

## 13.1 题目库存规则

- 每用户 READY 题目目标至少 7 道；低于 3 道触发高优先补充。

- 库存不足时减少突击，不得将 DRAFT、未查重或无来源题投放。

- READY 题超过 valid_until 自动回退 VERIFIED_REQUIRED。

- 题目曝光后立即从库存移除，不论用户是否完成。

## 13.2 数据清理

> **1.** scheduler 查询达到 retention_at 的音频，先标记 DELETION_PENDING。
>
> **2.** 确认没有进行中的评审或申诉依赖该音频。
>
> **3.** 删除物理文件并写 audit log；失败进入重试。
>
> **4.** 保留转写、指标和缺陷证据，除非用户删除整条训练。
>
> **5.** 账号删除采用异步删除任务，完成后返回删除证明。

# 14. 故障处理 SOP

| **故障**         | **标准处理**                                                                                           |
|------------------|--------------------------------------------------------------------------------------------------------|
| 通知未到达       | 检查 subscription active、浏览器权限、Service Worker、VAPID、push response；允许用户手动进入，不扣分。 |
| 麦克风权限拒绝   | 显示系统设置引导；不创建 attempt。                                                                     |
| 录音文件为空     | 前端校验 blob.size；服务端拒绝并允许重录，因为尚未形成有效第一答。                                     |
| 上传中断         | 保留本地 blob；同 attempt_id 重试，服务端幂等。                                                        |
| STT失败          | 重试 2 次；切备用 Provider；仍失败则 INVALID，不评分。                                                 |
| Graph卡住        | 查 thread_id、最新 checkpoint、pending ai_job；不得直接改 checkpoint 表，优先重试业务 job。            |
| 重复副作用       | 检查 interrupt 前代码和幂等键；补唯一约束和回归测试。                                                  |
| 来源不可访问     | 若未曝光则撤题；若已完成则报告显示链接失效和已保存证据。                                               |
| 题目明显重复     | 作废、不计分、模板禁用、查重回归集新增样本。                                                           |
| 评审误判         | 暂停对应 occurrence 确认；新增 Golden Case；修复后重新评审但保留原版本。                               |
| 模型供应商不可用 | 切备用 Provider；如果无法保证结构化输出和质量，则暂停突击。                                            |
| 磁盘空间不足     | 暂停录音上传和题目生成；先扩容或清理到期音频，禁止静默丢文件。                                         |

# 15. 发布检查单

## 15.1 上线前

- □ SPEC 变更已同步；ADR 已更新。

- □ 数据库 migration 正向/回滚验证。

- □ 单元、集成、图、Prompt 回归和 E2E 全部通过。

- □ 生产环境 API Key、JWT、VAPID、LangGraph 密钥未提交 Git。

- □ 前端构建产物不含 DASHSCOPE_API_KEY；Codex 未读取或输出真实 .env。

- □ 题目来源支持率 100%，防重复回归通过。

- □ 评审问题均有 quote 和时间点。

- □ 备份已完成并可恢复。

- □ HTTPS、CORS、上传大小、音频目录权限正确。

- □ 用户删除、音频清理和申诉流程可用。

## 15.2 上线后

- □ /health 正常。

- □ 真实手机完成一整次训练。

- □ worker、scheduler 无持续失败。

- □ model_run 记录 provider、model、prompt_version。

- □ push、STT、报告耗时在可接受范围。

- □ 日志中无答案正文、密钥和私有音频 URL。

# 16. Definition of Done

| **项目 P0 完成定义：**不是“App 能打开”，而是系统能够稳定、可追溯地完成一次有真实来源、未重复的随机语音突击，并把经证据复核的问题沉淀到个人缺陷经验库。 |
|--------------------------------------------------------------------------------------------------------------------------------------------------------|

| **维度** | **完成条件**                                                         |
|----------|----------------------------------------------------------------------|
| 产品闭环 | 自动选题 → 随机通知 → 语音第一答 → 追问 → 最终答 → 报告 → 缺陷更新。 |
| 来源     | 全部题目事实有证据，答题后可追溯。                                   |
| 不重复   | 原题、同义改写、参数换皮、结构换皮测试通过。                         |
| 评审     | 逻辑、口语、应变分开；所有负面判断有原话时间点。                     |
| 记忆     | 缺陷跨场景累计，单次不武断定性，后续题由画像自动驱动。               |
| 恢复     | 页面、API 或 worker 中断后可按规则恢复，不重复副作用。               |
| 隐私     | 用户数据隔离、音频私有、可删除、日志脱敏。                           |
| 运维     | 备份、健康检查、失败任务、来源失效和申诉可处理。                     |

# 技术参考资料

- 附录 A. 阿里云线上模型接入 SOP

- 附录 B. Codex CLI 开发编排 SOP

**\[R1\]** [<u>LangGraph Overview</u>](https://docs.langchain.com/oss/python/langgraph/overview)

**\[R2\]** [<u>LangGraph Interrupts</u>](https://docs.langchain.com/oss/python/langgraph/interrupts)

**\[R3\]** [<u>LangGraph Persistence</u>](https://docs.langchain.com/oss/python/langgraph/persistence)

**\[R4\]** [<u>LangGraph Checkpointers</u>](https://docs.langchain.com/oss/python/langgraph/checkpointers)

**\[R5\]** [<u>FastAPI Features</u>](https://fastapi.tiangolo.com/features/)

**\[R6\]** [<u>MDN MediaRecorder</u>](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder)

**\[R7\]** [<u>Web Push Overview</u>](https://web.dev/articles/push-notifications-overview)

\[R8\] 阿里云百炼模型大全与 fun-asr / cosyvoice / text-embedding-v4

**\[R9\]** [<u>pgvector</u>](https://github.com/pgvector/pgvector)

\[R10\] 阿里云百炼文本生成、结构化输出与 OpenAI 兼容调用

# 附录 A. 阿里云线上模型接入 SOP

## A.1 前置准备

1.  在阿里云百炼创建 API Key，并确认调用地域和业务空间 WorkspaceId。

2.  使用业务空间对应的 OpenAI 兼容 Base URL；华北 2（北京）示例为 https://\<WorkspaceId\>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1。

3.  确认账号可调用 qwen3.5-plus、qwen3.6-plus、fun-asr、cosyvoice-v3.5-plus 和 text-embedding-v4。

4.  仓库只创建 .env.example；真实 .env 加入 .gitignore，并在本机/服务器手工填写。

5.  不要把 DASHSCOPE_API_KEY 放进 VITE\_\*、前端配置、Dockerfile、日志或任务文档。

## A.2 .gitignore 与秘密管理

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th># .gitignore<br />
.env<br />
.env.*<br />
!.env.example<br />
secrets/<br />
*.pem<br />
<br />
# 可选：真实密钥放在仓库外<br />
# ../thinking-coach-secrets/dev.env</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

| Codex CLI 在仓库中工作时只允许查看 .env.example。真实 .env 应由开发者手工维护；AGENTS.md 必须明确“禁止读取、打印、修改真实 .env”。 |
|------------------------------------------------------------------------------------------------------------------------------------|

## A.3 Settings 实现

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>from pydantic import SecretStr<br />
from pydantic_settings import BaseSettings, SettingsConfigDict<br />
<br />
class Settings(BaseSettings):<br />
ai_provider: str = "aliyun"<br />
ai_provider_mode: str = "aliyun"<br />
<br />
dashscope_api_key: SecretStr | None = None<br />
dashscope_base_url: str | None = None<br />
<br />
qwen_dialog_model: str = "qwen3.6-plus"<br />
qwen_question_model: str = "qwen3.5-plus"<br />
qwen_review_model: str = "qwen3.6-plus"<br />
qwen_verify_model: str = "qwen3.6-plus"<br />
qwen_fallback_model: str = "qwen3.5-plus"<br />
<br />
aliyun_asr_model: str = "fun-asr"<br />
aliyun_tts_model: str = "cosyvoice-v3.5-plus"<br />
aliyun_embedding_model: str = "text-embedding-v4"<br />
<br />
model_config = SettingsConfigDict(<br />
env_file=".env",<br />
env_file_encoding="utf-8",<br />
case_sensitive=False,<br />
extra="ignore",<br />
)<br />
<br />
def validate_ai(self) -&gt; None:<br />
if self.ai_provider_mode == "aliyun":<br />
if not self.dashscope_api_key or not self.dashscope_base_url:<br />
raise RuntimeError("AI_CONFIG_MISSING")<br />
if "&lt;WorkspaceId&gt;" in self.dashscope_base_url:<br />
raise RuntimeError("AI_BASE_URL_NOT_RESOLVED")</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

- 所有 Secret 使用 SecretStr；日志只能输出 has_key=true/false，不能输出真实值。

- API、Worker、Scheduler 共享同一 Settings；前端不读取这些变量。

- 测试环境使用 AI_PROVIDER_MODE=mock，注入固定 Mock Provider，不调用真实模型。

## A.4 Qwen Provider 实现步骤

6.  定义 LLMProvider 协议和 Pydantic 结构化返回类型。

7.  使用 AsyncOpenAI(api_key, base_url, timeout, max_retries) 创建 AliyunQwenProvider。

8.  按任务选择 QWEN_DIALOG_MODEL、QWEN_QUESTION_MODEL、QWEN_REVIEW_MODEL 或 QWEN_VERIFY_MODEL。

9.  阿里云特有的 enable_thinking 等参数仅在 Provider 内映射，Graph 不感知供应商参数。

10. 捕获限流、超时、认证、结构化输出和服务异常，转换为稳定 error_code。

11. 主模型失败且符合降级条件时，只切换 QWEN_FALLBACK_MODEL；不放宽 Schema 和评分门槛。

## A.5 云端 ASR/TTS/Embedding 实现步骤

| **Provider**            | **实现要求**                                                            | **验收**                                                  |
|-------------------------|-------------------------------------------------------------------------|-----------------------------------------------------------|
| AliyunFunASRProvider    | 上传录音或生成短时可访问 URL，提交 fun-asr，轮询/获取结果并解析时间戳。 | 中文录音转写可回放定位；热词和错误映射可配置。            |
| AliyunCosyVoiceProvider | 将题目/追问转成音频；缓存同一 question_version 的结果。                 | 手机可播放；失败时可降级为浏览器 speechSynthesis 或文字。 |
| AliyunEmbeddingProvider | 批量调用 text-embedding-v4；记录模型和向量维度。                        | 相同文本稳定返回同维向量；pgvector 可写入和查询。         |
| OSS Adapter（可选）     | 私有 Bucket、最小权限 RAM、15 分钟以内签名 URL。                        | 未授权 URL 无法访问；日志不出现 Secret。                  |

## A.6 Smoke Test

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th># 不打印密钥，只输出模型、耗时和成功状态<br />
uv run python -m app.scripts.smoke_ai --provider aliyun --task llm<br />
uv run python -m app.scripts.smoke_ai --provider aliyun --task embedding<br />
uv run python -m app.scripts.smoke_ai --provider aliyun --task tts<br />
uv run python -m app.scripts.smoke_ai --provider aliyun --task asr --audio tests/fixtures/zh-short.webm</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

- LLM：返回符合 Pydantic Schema 的最小 JSON。

- Embedding：向量维度与数据库列匹配。

- TTS：输出非空音频且可播放。

- ASR：输出文本和至少片段级时间戳。

- 任一失败则 Provider 状态为 DEGRADED；正式题目库存和突击调度不得启动。

## A.7 模型切换 SOP

12. 先在开发环境修改对应 QWEN\_\*\_MODEL，不修改代码。

13. 运行 Provider 合约测试、Golden Set 和至少 5 次评分稳定性测试。

14. 比较问题编码、证据命中、结构化成功率、延迟和成本。

15. 通过后更新 ADR 和 .env.example 的推荐值，再部署并观察真实训练。

16. 异常时回滚环境变量到上一模型；不删除历史 model_run。

## A.8 常见故障

| **故障**         | **检查顺序**                                                       | **标准处理**                                  |
|------------------|--------------------------------------------------------------------|-----------------------------------------------|
| 401/鉴权失败     | API Key 是否为空、是否属于当前业务空间、环境变量是否在进程中生效。 | 停止重试；修复配置后人工重新执行 job。        |
| 404/模型不可用   | 模型 ID 拼写、地域/业务空间是否开放该模型。                        | 切回已验证模型 ID，不在代码中临时改名。       |
| 结构化输出失败   | Schema 是否过复杂、Prompt 版本、模型是否支持结构化输出。           | 同模型修复一次，再走配置化 fallback。         |
| ASR 无法读取音频 | 格式、文件大小、签名 URL、Bucket 权限和过期时间。                  | 重新转码/签名；不得把 Bucket 改为公开。       |
| 限流或超时       | provider request_id、并发、重试间隔。                              | 指数退避；保持 job 状态；不重复创建业务记录。 |

# 附录 B. Codex CLI 开发编排 SOP

## B.1 开发总原则

| 不要让 Codex “开发整个项目”。把 SPEC/SOP 转换成一系列边界清晰、可测试、可审查的纵向任务；一次会话只完成一个任务，一次提交只包含一个可解释增量。 |
|-------------------------------------------------------------------------------------------------------------------------------------------------|

- Codex 负责阅读代码、制定计划、实现、测试和审查；用户负责范围批准、密钥、产品判断和最终合并。

- 同一阶段未通过退出条件前，不进入下一阶段。

- 固定测试题、Mock 模型响应和 Golden Case 可以进入测试目录，但不得进入正式题库。

- 真实模型密钥不提供给 Codex；真实 smoke test 由用户手工执行。

## B.2 Codex 初始配置

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th># PowerShell 或 WSL 中确认安装<br />
codex --version<br />
codex doctor<br />
<br />
# ~/.codex/config.toml<br />
model = "gpt-5.5"<br />
approval_policy = "on-request"<br />
sandbox_mode = "workspace-write"<br />
web_search = "cached"<br />
<br />
[windows]<br />
sandbox = "elevated"</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

- 首次从仓库根目录运行 codex，然后使用 /init 生成 AGENTS.md 初稿，再替换为项目规则。

- 复杂任务先使用 /plan；计划确认后在同一会话实现。

- 日常禁止 --yolo 和 danger-full-access；只有隔离虚拟机中的一次性实验才可考虑。

- 需要最新官方资料时对单次任务启用搜索，并要求将采用的版本与来源写入 ADR。

## B.3 仓库内 Codex 文件

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>thinking-coach/<br />
├── AGENTS.md<br />
├── apps/web/AGENTS.md<br />
├── services/backend/AGENTS.md<br />
├── services/backend/app/graphs/AGENTS.md<br />
├── docs/<br />
│ ├── SPEC.md<br />
│ ├── SOP.md<br />
│ ├── progress.md<br />
│ ├── PLANS.md<br />
│ └── tasks/<br />
│ ├── P00-bootstrap.md<br />
│ ├── P01-cloud-providers.md<br />
│ └── ...<br />
└── .codex/<br />
└── task-report.schema.json # 可选</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## B.4 根 AGENTS.md 必须包含

- 先阅读 docs/SPEC.md、docs/SOP.md 和当前 docs/tasks/Pxx.md。

- 只能实施当前任务；不得顺手实现后续阶段或大范围重构。

- 不得读取、打印、修改 .env、secrets、真实用户音频和生产数据库。

- 禁止引入本地模型、GPU 依赖、Celery/Redis/Kafka、微服务或新的生产依赖，除非任务明确批准。

- domain 不依赖 FastAPI/LangGraph/模型 SDK；graphs 只编排；Provider 负责外部模型差异。

- 所有数据库变更使用 Alembic；所有结构化模型输出必须 Pydantic 校验。

- 完成前运行测试、lint、type-check 和 /review，并报告真实结果。

## B.5 Codex 开发阶段安排

| **任务**           | **Codex 实施范围**                                                            | **退出门**                                            |
|--------------------|-------------------------------------------------------------------------------|-------------------------------------------------------|
| P00 工程骨架       | Monorepo、FastAPI/Vue、Docker Compose、CI、AGENTS、health。                   | 前后端启动；检查命令全部通过。                        |
| P01 云模型配置     | Settings、Provider 协议、AliyunQwen/FunASR/CosyVoice/Embedding 适配器、Mock。 | 无真实 Key 的合约测试通过；用户手工 smoke test 通过。 |
| P02 数据库与账号   | Alembic、用户、邀请码、JWT、训练策略、强制 user_id 过滤。                     | 两个用户不可互访。                                    |
| P03 语音纵向切片   | PWA 录音、上传、幂等 attempt、本地私有音频和回放。                            | 真机连续录音与断网重试通过。                          |
| P04 转写与口语指标 | fun-asr 调用、时间戳、原稿/校正版、可计算指标。                               | 评审可定位原音频片段。                                |
| P05 LangGraph 会话 | 第一答、追问、最终答、interrupt/resume、checkpoint、幂等。                    | 进程重启后可恢复且无重复记录。                        |
| P06 严格评审       | Rubric、结构提取、逻辑/口语/应变、证据复核、Python 封顶。                     | 所有负面判断有 quote + 时间点。                       |
| P07 缺陷经验库     | definition、occurrence、profile、优先级、历史匹配。                           | 跨场景累计，单次不武断确认。                          |
| P08 来源与出题     | 来源抓取、Claim、验证、候选题、Rubric、来源公开。                             | 事实支持率 100%。                                     |
| P09 永不重复       | 哈希、Embedding、指纹、LLM 终审、模板 denylist。                              | 换皮回归集全部拦截。                                  |
| P10 随机突击       | 库存、APScheduler、Web Push、曝光退役、接受/过期。                            | 用户无法预知类型，漏接不扣分。                        |
| P11 报告与发布     | 周报、申诉、删除、备份、HTTPS、部署和恢复。                                   | 生产端到端验收通过。                                  |

## B.6 每个任务的标准执行循环

17. 用户创建分支 feat/Pxx-name，并写 docs/tasks/Pxx-name.md。

18. 启动新的 Codex 会话，要求只读 SPEC/SOP、AGENTS 和本任务文件。

19. 使用 /plan：Codex 输出当前理解、影响文件、数据库/接口变化、测试和风险；此阶段不改代码。

20. 用户确认范围后，要求 Codex 实现计划；禁止新增未批准范围。

21. Codex 运行任务文件规定的 lint、type-check、test、migration 和 build。

22. 运行 /review 审查未提交修改，修复高/中优先级问题并重新测试。

23. 用户人工检查 diff、真实手机或真实 API smoke test，然后提交。

24. 更新 docs/progress.md，并为下一任务开启全新会话；只有同一任务追修才使用 codex resume --last。

## B.7 单次任务提示词模板

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>你现在只执行任务 Pxx：&lt;任务名称&gt;。<br />
<br />
Goal<br />
- &lt;本次唯一目标&gt;<br />
<br />
Context<br />
- 先阅读 AGENTS.md、docs/SPEC.md、docs/SOP.md、docs/tasks/Pxx.md。<br />
- 重点目录：&lt;目录或文件&gt;。<br />
<br />
Constraints<br />
- 不读取或修改 .env / secrets。<br />
- 不实现任务范围外功能，不做无关重构。<br />
- 不新增生产依赖，除非先说明理由并获得批准。<br />
- 所有数据库变更使用 Alembic。<br />
- 所有外部模型通过 Provider；禁止本地模型。<br />
<br />
Out of scope<br />
- &lt;明确不做的内容&gt;<br />
<br />
Done when<br />
- &lt;可执行验收条件&gt;<br />
- 必须运行：&lt;测试命令&gt;。<br />
- 必须审查 diff，并汇报修改文件、测试结果、风险和未完成项。<br />
<br />
先进入计划阶段，不要立即修改代码。</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## B.8 代码审查和提交纪律

- Codex 实现会话和 review 会话分开；使用 /review 检查未提交修改。

- 用户在 review 通过后手工提交；默认不允许 Codex 自动 git commit、push、rebase 或 force push。

- 每次提交应能独立测试和回滚；迁移、Prompt、Schema 和代码必须在同一提交中保持一致。

- 发现 Codex 重复犯错两次时，先复盘并更新 AGENTS.md，而不是继续增加一次性提示词。

## B.9 并行任务规则

- 个人开发默认串行，避免两个 Codex 会话同时修改同一工作树。

- 确需并行时使用 git worktree，为每个任务创建独立分支和目录。

- 并行任务不得同时修改数据库基础模型、公共 Schema、同一 Graph 或同一 Provider。

- 合并前先在主集成分支运行全量回归和 /review。

## B.10 codex exec 的使用边界

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th># 只用于已经稳定、范围清晰的任务或自动检查<br />
codex exec --cd . --sandbox workspace-write --output-last-message artifacts/codex-Pxx-report.md - &lt; docs/tasks/Pxx.md<br />
<br />
# 同一任务追修<br />
codex exec resume --last "根据 review 结果修复问题并重新运行测试"</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

- P00-P06 首次实现优先使用交互式 codex，不直接使用 exec 无人值守开发。

- 任何时候都不要使用 --dangerously-bypass-approvals-and-sandbox / --yolo。

- exec 输出只能作为任务报告，最终仍需人工查看 diff 和测试结果。

## B.11 Codex 阶段完成检查单

- □ 当前任务文件中的所有 Done when 已逐项验证。

- □ 没有修改真实 .env、密钥、用户音频和生产数据。

- □ 没有实现下一阶段功能或引入未批准依赖。

- □ 测试、lint、type-check、build 和 migration 检查均有真实输出。

- □ /review 无未处理高/中优先级问题。

- □ SPEC/SOP/ADR/progress 与实际代码一致。

- □ 用户已人工检查关键逻辑并完成提交。

# 附录 C. Python 依赖管理 SOP

## C.1 首次初始化

在 `services/backend` 执行：

```powershell
uv --version
uv python install 3.12.13
uv python pin 3.12.13
uv lock
uv sync --all-groups
uv run python scripts/verify_dependency_policy.py
```

Windows 也可以直接运行：

```powershell
./scripts/bootstrap.ps1
```

首次成功后提交 `pyproject.toml`、`.python-version` 与 `uv.lock`。本包不附带伪造锁文件；必须由真实解析生成。

## C.2 日常开发和 CI

```powershell
uv lock --check
uv sync --locked --all-groups
uv run python scripts/verify_dependency_policy.py
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

CI 不得使用会重新解析或升级依赖的命令。

## C.3 LangGraph / LangChain 使用规则

1. 允许使用 `langgraph.graph.StateGraph`、`START`、`END`、`interrupt()`、Postgres Checkpointer 和自定义 State。
2. `langchain-core==1.4.8` 是显式固定的基础运行依赖；不得把它误解为已经启用完整 LangChain Agent 框架。
3. 模型调用继续使用 `openai` / `dashscope` SDK 与自定义 Provider；不要新增 `langchain`、`langchain-openai`、`ChatOpenAI` 或 `langchain.agents`。
4. 不得用 LCEL 或预构建 Agent 替换来源核验、防重复、评分封顶、缺陷累计等确定性流程。
5. 如任务确实要求完整 LangChain，先暂停编码，提交 ADR 和依赖变更说明，获得批准后再修改 `pyproject.toml` 与 `uv.lock`。

验证命令：

```powershell
uv run python -c "import langgraph, langchain_core; print('langgraph/core ok')"
uv run python -c "import importlib.util; assert importlib.util.find_spec('langchain') is None"
```

## C.4 新增依赖

1. 建立独立任务，不与业务功能混在同一提交。
2. 说明为何标准库和已有依赖无法满足。
3. 核对许可证、维护状态、Python 3.12 支持和替代方案。
4. 选定精确版本后运行 `uv add "package==x.y.z"`。
5. 运行 `uv lock`，审查 `pyproject.toml` 与 `uv.lock` diff。
6. 运行全量质量检查和受影响的集成/图恢复/Golden Case 测试。
7. 更新 `DEPENDENCIES.md`、`direct-pins.txt` 和必要 ADR。

## C.5 升级依赖

- 一次只升级一个逻辑依赖族，不使用无目标的全量升级。
- LangGraph 或 Checkpointer 升级必须回归 interrupt、resume、重放和幂等。
- FastAPI/Pydantic 升级必须回归 OpenAPI、Settings、请求响应 Schema。
- SQLAlchemy/Alembic/驱动升级必须回归迁移升降级与事务。
- OpenAI/DashScope/OSS 升级必须回归 Fake Provider 合约，真实调用仅通过手工 smoke test。
- 出现无关锁文件变化时停止、回退并查明原因。

## C.6 Codex 执行提示

```text
本任务不得新增或升级依赖。先读取 docs/DEPENDENCY_POLICY.md 和 services/backend/pyproject.toml。
必须使用现有 uv.lock；若锁文件缺失，只能在 P00 中真实生成。
任何 pyproject.toml 或 uv.lock 变化都要先报告原因并等待批准。
```

