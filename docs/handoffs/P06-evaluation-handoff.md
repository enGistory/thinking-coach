# P06 严格证据化评审交接

## 状态
- 交接状态：VERIFIED，可交接。
- 分支：`codex/p06-evaluation`
- 基线：`86c7e9a feat: 完成 P05 LangGraph 会话闭环`（当前 `dev` 与 `HEAD` 一致，P06 为未提交改动）。
- 提交与合并状态：未提交；未执行 commit、push、merge、release。合并前需要先由用户人工检查 diff 并按项目流程提交。

## 业务结果
- P05 的三阶段语音答辩闭环已接入 P06 严格评审：最终答完成后进入 `EVALUATING`，由 worker 幂等创建并执行 `EVALUATE_SESSION` job。
- 系统会冻结开发用 rubric，提取回答结构，执行逻辑评审、口语统计、追问应变评分，并用 Python 确定性规则完成证据复核、三类独立分数和硬封顶。
- 负面评价候选只有在 `quote + start_ms/end_ms + confidence + missing_information + correction_rule` 能被转写片段支持时才会写入最终 issue；无 quote 或时间点无效的批评会被拒绝。
- 每次结构化评审调用记录到 `model_run`，报告写入 `evaluation_report`，问题证据写入 `evaluation_issue`。

## 主要实现范围
- Database：新增 P06 Alembic 迁移 `0005_evaluation.py`，创建 `question_rubric`、`evaluation_report`、`evaluation_issue`、`prompt_version`、`model_run`；修复 Alembic online/offline context 的 `public` schema/search_path，使 P06 upgrade/downgrade/upgrade 可重复通过。
- Models/Repository：扩展 `services/backend/app/db/models.py`，新增 `services/backend/app/repositories/evaluations.py`；评审写入使用 session/report 级唯一约束和 issue 证据唯一键，`evaluation_issue` 证据唯一键包含 `attempt_id`，允许不同回答阶段出现相同 quote/time。
- Schema/Domain：新增 `services/backend/app/schemas/evaluation.py`、`services/backend/app/domain/evidence.py`、`services/backend/app/domain/scoring.py`；证据复核支持同一时间范围内的 quote 校验和相邻 segment 跨段 quote，分数封顶由 Python 规则控制。
- Service/Worker：新增 `services/backend/app/services/evaluation.py`；扩展 `services/backend/app/workers/main.py` 和 `services/backend/app/repositories/jobs.py` 支持 `EVALUATE_SESSION`。
- API/Flow：扩展训练流程，P05 最终答 resume 后把 session 推进到 `EVALUATING`，评审成功后进入 `COMPLETED`。
- Prompt/Golden：新增 `prompts/answer_structure`、`prompts/logic_review`、`prompts/adaptability_review`、`prompts/evidence_verification` 的 v1.0.0 文件；新增 `services/backend/tests/golden_cases/p06_evaluation_cases.json`。
- Tests：新增 `tests/test_evaluation_p06.py`、`tests/test_evaluation_rules_p06.py`、`tests/test_migrations_p06.py`，并扩展 P05/P04 相关回归。

## Review 与修复结果
- `/review` 曾发现：证据 verifier 可能接受 quote 来自一个 segment、时间点来自另一个 segment；已修复为只在时间覆盖范围内匹配 quote，并补充回归测试。
- `/review` 曾发现：跨相邻 segment 的合法 quote span 被拒绝；已修复为支持连续相邻片段范围，并补充回归测试。
- `/review` 曾发现：`answer_structure` prompt 字段名与 `AnswerStructure` schema 不一致；已修复 prompt 字段并补充回归测试。
- 后续 `$project-fix` 修复迁移回滚问题：Alembic context 固定 `public` schema/search_path，并在 `SET search_path` 后提交，避免 SQLAlchemy 2 隐式事务导致 DDL 被回滚。
- 后续 `$project-fix` 修复 `evaluation_issue` 唯一约束漏掉 `attempt_id` 的问题，并补充不同 attempt 相同 quote/time 可同时入库的回归测试。
- 后续 `$project-fix` 修复中文最终回答无法获得应变关键词加分的问题，补充 `未知`、`依据`、`证据`、`取舍`、`下一步` 等中文标记，并补充中文 final answer 回归测试。
- 当前无未处理的 acceptance-blocking review finding。

## 验收证据
- `cd services/backend && uv run ruff check .`：通过，`All checks passed!`
- `cd services/backend && uv run ruff format --check .`：通过，`75 files already formatted`
- `cd services/backend && uv run mypy app`：通过，`Success: no issues found in 58 source files`；保留既有 unused section 提示。
- `cd services/backend && uv lock --check`：通过。
- `cd services/backend && uv run python scripts/verify_dependency_policy.py`：通过。
- `cd services/backend && TEST_DATABASE_SYNC_URL=postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test uv run pytest tests/test_migrations_p06.py -q`：通过，`1 passed`。
- `cd services/backend && TEST_DATABASE_URL=postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking_test TEST_DATABASE_SYNC_URL=postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test uv run pytest -q`：通过，100% passed。
- `cd services/backend && TEST_DATABASE_URL=postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking_test TEST_DATABASE_SYNC_URL=postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test uv run pytest tests/test_evaluation_p06.py tests/test_evaluation_rules_p06.py -q`：通过，`12 passed`。
- `cd apps/web && pnpm lint`：通过。
- `cd apps/web && pnpm type-check`：通过。
- `cd apps/web && pnpm test`：通过，`6 files / 17 tests`。
- `cd apps/web && pnpm build`：通过，Vite/PWA build passed。
- `git diff --check`：通过。
- `RUN_LIVE_AI_TESTS=1` 配置探测：已执行，不读取 `.env`。当前进程环境缺少 Aliyun/Qwen/DashScope 必需配置，返回 `AI_CONFIG_MISSING`，因此真实线上模型 smoke 未执行成功。
- MuMu 12 端到端重新验证：通过。使用 ADB 设备 `127.0.0.1:16384`，通过 `adb reverse tcp:5182 tcp:5182` 与 `adb reverse tcp:8010 tcp:8010` 访问 Web `http://127.0.0.1:5182/` 和 API `http://127.0.0.1:8010`；临时库 `thinking_mumu_p06_reverify_153327`，测试账号 `mumu-p06-reverify-153327`；完成登录、第一答、追问答、最终答、上传、转写、评审和报告入库。验收结束后临时 API/Web/worker 已停止，反向端口已移除。
- MuMu 入库证据：session `64e4513b-0100-4cbd-b912-afe985e3ad15` 为 `COMPLETED`；`evaluation_report` `751ccf15-256d-4473-a49f-f52d88593b6b` 为 `COMPLETED`；3 条 `voice_attempt` 均 `UPLOADED`；3 条 `attempt_transcript` 均 `SUCCEEDED`；1 条 `EVALUATE_SESSION` job 为 `SUCCEEDED`；2 条 `model_run` 均 `structured_ok=true`；mock LLM 本轮 `evaluation_issue` 为 0；分数为 logic `100`、speech `80`、adaptability `70`、final `90`。

## Done When 映射
- 所有负面问题有逐字稿原句和有效时间点：通过。`test_evaluation_p06.py` 和 `test_evaluation_rules_p06.py` 覆盖有效 quote、缺失 quote、quote 不匹配、时间点错误、quote 与时间片段不一致、跨 segment quote 等路径；最终 issue 写入前必须通过确定性 verifier。
- 不存在 quote 的批评被 verifier 拒绝：通过。单元测试和服务测试均覆盖拒绝逻辑，并确认无效证据不会落入最终 issue。
- 逻辑/口语/应变分数独立；封顶规则有单元测试和 Golden Case：通过。测试覆盖三类分数独立保存、`ALIGN-01` 硬封顶、中文 final answer 应变关键词加分；Golden case 覆盖答非所问封顶、框架空泛封顶、追问后有效修正和高质量无负面问题。
- 数据库可回滚：通过。P06 专项迁移测试验证 upgrade head、downgrade -1、再次 upgrade head。
- 必须使用 MuMu 验收：通过。本次不沿用 P03-P05 记录，重新用 MuMu 完成 P03-P06 用户路径。

## 未运行与不适用项
- 真实阿里云模型 live smoke 未执行成功：已设置 `RUN_LIVE_AI_TESTS=1` 做安全配置探测，但当前进程环境缺少 Aliyun/Qwen/DashScope 必需配置，返回 `AI_CONFIG_MISSING`；未读取真实 `.env` 或密钥。
- 未使用 iPhone 或物理 Android 真机：本次用户指定使用 MuMu，已满足强制模拟器验收。
- 未执行 commit、push、PR、release 或生产部署。
- 未实现 P07 缺陷经验库、P08 真实来源出题、P09 防重复、P10 随机突击、P11 报告发布。

## API、数据库、配置、依赖影响
- API：训练状态增加 `EVALUATING`/`COMPLETED` 流转；现有前端通过状态轮询看到评审完成。本阶段没有新增正式报告读取 API。
- 数据库：新增 P06 评审相关业务表；Alembic downgrade 会移除 P06 表，再次 upgrade 可恢复。
- 配置：未新增环境变量；继续使用既有 `DATABASE_URL`、`DATABASE_SYNC_URL`、`AI_PROVIDER_MODE` 和 Qwen review/verify model 配置。
- 依赖：未新增或升级生产依赖；`uv.lock` 通过 `--check`。
- 运行：P06 正常流依赖 API、worker、PostgreSQL、Provider bundle、音频存储；评审由 worker 异步执行，API 不长时间阻塞。

## 已确认不做
- 不做缺陷 occurrence/profile 累计和稳定缺陷确认；留给 P07。
- 不做正式来源、自动出题、来源公开或事实支持率 100% 流程；留给 P08。
- 不做题目防重复、embedding 查重或结构换皮终审；留给 P09。
- 不做随机突击调度、Web Push、过期/曝光退役；留给 P10。
- 不做完整报告页、申诉、删除、备份恢复、HTTPS 发布；留给 P11。
- 不引入本地模型、GPU、完整 LangChain Agent、Celery/Redis/Kafka/RabbitMQ 或新的生产依赖。

## 已知风险
- MuMu 端到端验收使用 mock STT/LLM，只证明本地闭环、状态流转和入库路径；真实模型输出质量、真实 ASR 内容和真实负面 issue 生成仍需后续受控 smoke test。
- 本次 mock LLM 未生成负面 issue，端到端库中 `evaluation_issue=0`；负面评价 quote/start/end 证据由后端单元和集成测试覆盖。
- 临时 MuMu 验收库 `thinking_mumu_p06_reverify_153327` 保留在本地 Docker PostgreSQL 中作为证据；生产合并前不应把它视为生产数据。
- 既有 Starlette/httpx、Alembic `path_separator` 与 mypy unused section 提示仍存在，当前不阻塞 P06。

## 回滚方式
- 代码层：revert P06 提交，移除 P06 schema/domain/service/repository/worker/job/prompt/golden/test 改动，并恢复 P05 最终答后直接完成或停在 P05 原行为。
- 数据库层：执行 Alembic `downgrade -1`，移除 P06 表；如已存在未处理 `EVALUATE_SESSION` job，先停 worker/API，再清理或忽略相关 P06 job。
- 运行层：若评审服务异常，可临时停止 worker 的 `EVALUATE_SESSION` 领取路径，保留 P05 语音答辩和 P04 转写能力。

## 下一任务建议
- 推荐进入 P07：缺陷经验库。
- 前置条件：P05/P06 本地提交并合并到集成分支；确认 P06 迁移已在目标测试库升降级通过；若 P07 要消费 evaluation issue，需要先决定 mock 无负面 issue 时的开发 fixture/seed 策略。
