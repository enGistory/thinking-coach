# P08 真实来源、事实原子与自动出题计划

Status: APPROVED
Approval date: 2026-06-23

## 摘要

- 目标：把当前硬编码开发测试题替换为正式的“来源检索 -> 内容抓取/解析 -> Claim 提取与独立验证 -> 候选题生成 -> 逐句事实映射 -> Rubric 冻结 -> READY 题绑定训练会话”链路。
- 用户可见结果：有 READY 题时，训练会话展示真实来源支持的题目；完成最终回答后，用户可查看完整来源、Claim 证据定位和加工说明。
- 明确不做：不实现 P09 四级防重复/LLM 终审，不实现 P10 随机突击/推送库存调度，不允许用户选择题型、领域、缺陷或难度。
- 已确认决策：SearchProvider 使用博查 AI Web Search API；官方接口为 `https://api.bochaai.com/v1/web-search`，Bearer Key 鉴权，结果含 `webPages.value`。参考：[博查 AI 开放平台](https://open.bochaai.com/)。
- 当前事实：P07 已 VERIFIED；当前训练图仍使用开发题，`ProviderBundle` 尚无 SearchProvider；项目已有 `httpx`、`trafilatura`、`pymupdf`，预计不新增生产依赖。

## 关键变更

- 配置与 Provider：
  - 新增后端配置：`SEARCH_PROVIDER=bocha|mock`、`BOCHA_API_KEY`、`BOCHA_SEARCH_ENDPOINT`、`BOCHA_SEARCH_COUNT`、`BOCHA_FRESHNESS`、`RUN_LIVE_SEARCH_TESTS`。
  - 扩展 Provider Bundle，加入 `SearchProvider`；新增 `BochaSearchProvider`、`MockSearchProvider`、`ContentFetcher` Protocol 和 HTTP/PDF/网页解析实现。
  - Bocha 只返回候选 URL 与摘要；正式证据必须来自后续 `ContentFetcher` 抓取正文/PDF，不使用搜索摘要作为 Claim 证据。
- 数据库与冻结模型：
  - 新增 Alembic `0007_source_question`：创建 `source_bundle`、`question_source`、`source_claim`、`question`、`question_claim_map`、`question_fingerprint`。
  - 扩展 `question_rubric`：支持题目级 Rubric 在 session 创建前冻结；保留现有 session 级 dev rubric 兼容路径。
  - 给 `training_session.question_id` 建正式 FK；所有 question/source 查询按 `user_id` 或 owned session 过滤。
  - `question.status` 最小状态流为 `DRAFT -> VERIFIED -> DEDUPED -> READY -> EXPOSED/RETIRED/INVALID`；P08 的 `DEDUPED` 只做 normalized hash/source event 基础门槛，完整四级查重留给 P09。
- 出题工作流：
  - 新增 `PREPARE_QUESTIONS` worker job，幂等生成 8-12 个候选题；目标缺陷来自当前用户最高优先级 profile，没有 profile 时使用确定性 bootstrap 缺陷集。
  - Prompt/Schema 分离为 search direction、claim extraction、claim verification、question generation、rubric generation；Claim verifier 使用独立 `verify` 模型槽。
  - Domain 规则控制来源等级、B 级关键事实交叉验证、`UNSUPPORTED` 禁止入题、`unsupported_claim_count == 0` 才能 READY。
  - `POST /api/v1/trainings/current`：有 active session 则返回；否则绑定一个当前用户 READY 题并初始化图；无 READY 时 enqueue prepare job 并返回明确 `QUESTION_NOT_READY`，不回退为无来源开发题。
  - `voice_training` 图从 frozen question 读取首题文本；评审服务优先使用题目级 frozen Rubric，开发测试路径仅作为无正式 question 的兼容分支。
- API 与前端：
  - `TrainingStateResponse` 可带最小来源摘要：来源数量、最高等级、bundle 凭证编号；不返回 URL、标题、Claim、目标缺陷。
  - 新增 `GET /api/v1/trainings/{id}/provenance`：仅在 owned session `COMPLETED` 后返回来源列表、Claim、locator、excerpt、support_status 和 question-claim mapping。
  - 前端仅做最小展示：训练中不提前泄露来源内容；完成后自动拉取并展示 provenance。继续保持语音优先和第一答不可覆盖。

## 测试与验收

- Domain 单测：来源等级、C 级不能作为确认事实、B 级关键事实缺少交叉来源不 READY、unsupported claim 淘汰、所有题目句子必须有 Claim 映射。
- Provider/Fetcher 测试：Bocha 响应映射、401/429/超时错误码、HTML 正文提取、PDF 页码 locator、抓取失败关闭、snapshot hash 稳定。
- Service/worker 集成测试：无来源不产生 READY；mock 搜索+抓取+LLM payload 可生成 8-12 个候选并冻结 Rubric；重复 job 不重复写入 question/source/claim；READY 被 session 绑定后不可再次分配。
- API 测试：两个用户互不可见；无 READY 返回 `QUESTION_NOT_READY`；`state` 只暴露来源摘要；`provenance` 在完成前拒绝、完成后返回完整映射。
- 前端测试：训练状态类型扩展、无 READY 错误提示、完成后 provenance 展示；不在回答前显示 URL/标题/Claim。
- 迁移测试：`upgrade head -> downgrade 0006_defect_memory -> upgrade head`，验证新增表、FK、唯一约束和 `question_rubric` 兼容。
- Golden 回归：新增 P08 golden cases，覆盖 verified claim 成题、unsupported claim 拒题、B 级单来源关键事实拒题。
- 必跑命令：后端 `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app`、`uv run pytest -q`、`uv lock --check`、依赖策略脚本；前端如改动则跑 `pnpm lint`、`pnpm type-check`、`pnpm test`、`pnpm build`；数据库跑 Alembic upgrade/downgrade/upgrade；最后执行独立 `/review`。
- 可选 live smoke：仅当 `RUN_LIVE_SEARCH_TESTS=1` 且环境提供 `BOCHA_API_KEY` 时调用博查一次非敏感公开查询；未设置时记录“未运行”，不伪造通过。

## Done When 映射

- 每个事实可定位原始证据：`source_claim.locator/excerpt/support_status` 与 `question_claim_map` 强制覆盖题目事实句；测试验证缺少映射不能 READY。
- 无合格来源时不产生 READY 题：Search/Fetch/Parse/Verify 任一失败或 `unsupported_claim_count > 0` 时，question 保持非 READY；API 不会分配。
- 题目、来源、Rubric、Prompt 版本在曝光前冻结：READY 前写入 source bundle、source hash、claims、question fingerprint、rubric content hash、prompt versions；session 绑定后才进入答题图。
- 答后公开来源：`provenance` 只允许 completed owned session 读取；前端完成后展示完整来源与 Claim 映射。

## 假设与停止条件

- 假设 P08 在 P07 当前结构上实施，实施前需重新检查工作区；若有无关未提交改动，先停止报告。
- 假设实现前创建/切换到 `codex/p08-source-question` 分支；不 commit、不 push、不发布。
- 假设不新增生产依赖、不读取真实 `.env`、不上传源码或用户数据到外部服务；API Key 只来自后端环境变量。
- 如果博查响应格式与官方页面不一致、需要新增付费/供应商合同决策、需要保存完整网页/PDF 原文、需要 P09 完整查重或 P10 推送调度，则停止并重新确认范围。
- 回滚方式：revert P08 代码，Alembic downgrade 到 `0006_defect_memory`；移除新增环境变量使用，不需要锁文件回滚。
