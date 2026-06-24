# P08 真实来源、事实原子与自动出题交接

## 状态

- 交接状态：VERIFIED。
- 分支：`codex/p08-source-question`。
- 提交与合并状态：未提交；未执行 commit、push、merge、release。
- 阻塞项：无。已完成多轮 review/fix/verify，最后一次带 `TEST_DATABASE_URL` 的 DB 集成、迁移验收与显式 live Bocha smoke 均通过。

## 业务结果

- 系统现在可以从真实来源检索、抓取和解析材料，提取 Claim，经独立验证后生成 READY 题与题目级冻结 Rubric。
- 无合格来源、抓取失败、unsupported claim、缺少事实映射或来源等级不足时，题目失败关闭，不会进入 READY。
- `POST /api/v1/trainings/current` 不再在无正式题时回退到无来源开发题；无 READY 题时会排队 `PREPARE_QUESTIONS` job 并返回 `QUESTION_NOT_READY`。
- 训练中只暴露最小来源摘要；用户完成最终回答后，owned completed session 才能读取完整 provenance，包括 source、claim、locator、excerpt 与 question-claim mapping。
- P08 只实现来源与出题基础链路；完整四级防重复、随机突击调度和推送库存策略分别留给 P09/P10。

## 主要实现范围

- Provider/Fetcher：扩展 `SearchProvider`、`ContentFetcher` 协议与 Provider bundle，新增 Bocha 搜索、mock 搜索、网页/PDF 抓取解析、snapshot hash 与 SSRF 防护。
- Domain：新增来源等级、B 级关键事实交叉验证、unsupported claim 淘汰、题目事实映射与 READY 门槛等确定性规则。
- Prompts：新增 `search_direction`、`claim_extraction`、`claim_verification`、`question_generation`、`rubric_generation` v1.0.0 prompt。
- Database：新增 Alembic `0007_source_question.py`，创建 `source_bundle`、`question_source`、`source_claim`、`question`、`question_claim_map`、`question_fingerprint`，并扩展 `question_rubric` 与 `training_session.question_id`。
- Repository/Service：新增 source question repository/service，支持 `PREPARE_QUESTIONS` job 幂等生成与 retry 复用 source bundle。
- API/Graph/Worker：训练创建绑定 READY 题；训练状态返回 source summary；新增 completed owned session provenance 查询；worker 支持 `PREPARE_QUESTIONS`。
- Frontend：扩展训练状态类型、无 READY 提示、完成后 provenance 展示，并保证答题前不显示 URL、标题或 Claim。
- Tests：新增 P08 DB 集成、provider/fetcher、domain rules、migration、golden cases、provenance 双用户隔离、live Bocha smoke gate。

## Review 与修复结果

- 已修复 DNS 解析后私网 SSRF 拦截问题，并补充回归覆盖。
- 已补 P08 Golden Case 回归，覆盖 verified claim 成题、unsupported claim 拒题、B 级单来源关键事实拒题。
- 已补 provenance 双用户隔离测试，确保其他用户无法读取 completed session provenance。
- 已修复 `prepare_questions_for_user` 重试幂等 credential：带 `job_id` 的 retry 复用既有 bundle 与原 search queries，不因模型第二次生成不同 search direction 而重复写入 source/question。
- 已修复 live Bocha smoke 入口，只在显式 `RUN_LIVE_SEARCH_TESTS=1` 且提供 `BOCHA_API_KEY` 时运行。
- 已修复 DB 集成测试自身缺少 `ai_job` 行导致的 `model_run.job_id` 外键失败；测试现在通过真实 `AIJobRepository.enqueue_prepare_questions()` 创建对应 job。

## 验收证据

- `cd services/backend && TEST_DATABASE_URL=postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking_test TEST_DATABASE_SYNC_URL=postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test uv run pytest tests/test_source_question_p08.py tests/test_source_question_provider_p08.py tests/test_source_question_rules_p08.py tests/test_migrations_p08.py -q -rs`：通过，`29 passed, 1 skipped`；skip 为未设置 live Bocha 环境时的门禁行为。
- `cd services/backend && uv run ruff check .`：通过，`All checks passed!`
- `cd services/backend && uv run ruff format --check .`：通过，`92 files already formatted`
- `cd services/backend && uv run mypy app`：通过，`Success: no issues found in 67 source files`；保留既有 unused section 提示。
- `cd services/backend && uv lock --check`：通过。
- `cd services/backend && uv run python scripts/verify_dependency_policy.py`：通过。
- `cd services/backend && TEST_DATABASE_URL=postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking_test TEST_DATABASE_SYNC_URL=postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test uv run pytest -q -rs`：通过，`117 passed, 1 skipped`；skip 为 live Bocha smoke 默认门禁。
- `cd apps/web && pnpm lint`：通过。
- `cd apps/web && pnpm type-check`：通过。
- `cd apps/web && pnpm test`：通过，`6 files passed, 19 tests passed`。
- `cd apps/web && pnpm build`：通过，生产构建和 PWA precache 生成成功。
- `cd services/backend && TEST_DATABASE_URL=postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking_test TEST_DATABASE_SYNC_URL=postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test uv run pytest tests/test_source_question_p08.py -q -rs`：通过，`9 passed`。
- `cd services/backend && TEST_DATABASE_SYNC_URL=postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test uv run pytest tests/test_migrations_p08.py -q -rs`：通过，`1 passed`。
- `cd services/backend && RUN_LIVE_SEARCH_TESTS=1 BOCHA_API_KEY=<redacted> uv run pytest tests/test_source_question_provider_p08.py::test_live_bocha_search_provider_smoke -q -rs`：通过，`1 passed`。
- `git diff --check`：通过。

## Done When 映射

- 每个事实可定位原始证据：通过。`source_claim.locator/excerpt/support_status` 与 `question_claim_map` 入库，P08 DB 集成、domain rules 和 Golden Case 覆盖缺少映射与 unsupported claim 拒题。
- 无合格来源时不产生 READY 题：通过。无搜索结果、抓取/解析失败、B 级关键事实缺少交叉验证、unsupported claim 均失败关闭。
- 题目、来源、Rubric、Prompt 版本在曝光前冻结：通过。READY 前写入 source bundle、source hash、claims、question fingerprint、rubric content hash 和 prompt versions；session 绑定后进入答题图。
- 答后公开来源：通过。`provenance` 仅允许 completed owned session 读取；前端完成后展示完整来源与 Claim 映射，训练中只显示摘要。

## 未完成与不适用项

- P09 四级防重复未实现；P08 仅做 normalized hash/source event 基础门槛。
- P10 随机突击、Web Push、接受/过期和曝光退役调度未实现。
- 来源错误、重复题、转写和评审的完整申诉 UX 留给 P11 报告与申诉阶段。
- 本次未做 MuMu/真机端到端验收；P08 以 API、DB、前端单测/build 和 live Bocha smoke 作为阶段验收证据。

## API、数据库、配置、依赖影响

- API：`POST /api/v1/trainings/current` 在无 READY 时返回 `QUESTION_NOT_READY` 并排队出题；`GET /api/v1/trainings/{id}/state` 返回最小 source summary；新增 `GET /api/v1/trainings/{id}/provenance`。
- 数据库：新增 P08 来源与题目表；`question_rubric` 支持题目级 Rubric；`training_session.question_id` 关联正式题。迁移可 downgrade 到 `0006_defect_memory` 后再次 upgrade。
- 配置：新增 `SEARCH_PROVIDER`、`BOCHA_API_KEY`、`BOCHA_SEARCH_ENDPOINT`、`BOCHA_SEARCH_COUNT`、`BOCHA_FRESHNESS`、`RUN_LIVE_SEARCH_TESTS`；真实 Key 仅允许后端环境变量提供。
- 依赖：未新增或升级生产依赖；`uv lock --check` 和依赖策略脚本通过。
- 隐私与安全：前端不接触 Bocha/API Key；训练完成前不泄露来源 URL、标题或 Claim；SSRF 防护包含重定向后和 DNS 解析后的私网地址拦截。

## 已知风险

- live Bocha smoke 只覆盖一次非敏感公开查询，不能代表供应商 SLA、额度、成本或所有响应变体；上线前仍建议配置监控和失败关闭告警。
- 本次 live smoke 的 Search API key 曾由用户在会话中显式提供；生产上线前建议按密钥治理轮换，并确认没有写入 Git、日志或文档。
- 真实网页/PDF 的正文抽取质量会随站点结构变化；当前策略是抓取/解析失败关闭并换来源，后续可建立来源失效巡检。
- P08 已支持基础 dedupe/fingerprint，但完整换皮题拦截仍依赖 P09。
- 存在既有 Starlette/httpx 与 Alembic `path_separator` deprecation warnings；不影响本阶段验收。
- 工作区仍未提交，且包含 P08 大量新增文件；合并前仍需人工复查 diff 并按项目流程提交。

## 回滚

- 代码回滚：revert P08 相关业务、前端、prompt、test 和配置改动。
- 数据库回滚：在目标环境执行 Alembic downgrade 到 `0006_defect_memory`，确认 `question_rubric` 与 `training_session` 回到 P07 兼容结构。
- 配置回滚：移除或忽略 P08 新增 Search/Bocha 环境变量，将训练创建恢复到 P07 行为前需同步回滚业务代码。
- 运营回滚：尚未曝光的 P08 READY 题可作废；已完成训练应保留当时 source/claim/rubric/prompt 版本作为审计证据。

## 下一任务建议

- 推荐进入 P09：永不重复。
- P09 前置：保留 P08 `question_fingerprint` 与 source event 信息，补 embedding/结构/答案骨架/LLM 终审回归集，确保 P08 READY 题不会因后续查重迁移丢失 provenance。
