# P09 题目永不重复与换皮拦截计划

Status: APPROVED
Approval date: 2026-06-24

## 摘要

- 目标：在 P08 来源出题链路上补齐四级防重复：规范化哈希、Embedding 精确近邻、结构指纹、LLM 终审，并支持用户标记“明显换皮”后作废题目、不计分、禁用模板家族。
- 用户可见结果：READY 题进入训练前已被完整查重；完成训练后，用户可在 PWA 中对明显换皮题发起重复投诉；投诉成功后该题不再计分，后续候选过滤会永久避开对应模板家族。
- 明确不做：不实现 P10 随机突击/Web Push；不新增生产依赖；不读取真实 `.env`；不引入本地模型、GPU、完整 LangChain Agent 或新的基础设施。
- 当前事实：P08 已 VERIFIED，`question_fingerprint` 已有 `normalized_hash`、`structural_json`、`template_family`、`source_event_id`；Provider 已有 `EmbeddingProvider`/Mock Embedding；完整 P09 尚未实现。
- 用户补充验收：P09 必须使用 MuMu 真机/模拟器路径验收，不用桌面浏览器测试替代。

## 关键变更

- 防重复规则与服务：
  - 新增 `app/domain/question_dedupe.py`，实现规范化、阈值、结构维度变化计算和判定：`cosine >= 0.92` 直接拒绝，`0.82 <= cosine < 0.92` 进入 LLM 终审；普通复测至少 4 个结构维度变化，高频/高优先缺陷至少 6 个。
  - `SourceQuestionService` 注入 `EmbeddingProvider`，在候选题 READY 前按顺序执行：denylist/source_event/hash 早拒绝 -> prompt/summary/decision embedding 精确近邻 -> 结构指纹 -> 必要时 LLM 终审。
  - LLM 终审使用 `verify` 模型槽、温度 0，新增 `dedupe_adjudication` Prompt 与 Pydantic Schema；若终审需要运行但模型失败或输出无效，候选题失败关闭，不进入 READY。
  - 查重历史按系统内全部已存题目指纹比较；LLM 终审只传最小历史题 prompt、fingerprint、rubric 摘要，不传用户回答、音频、转写或用户标识。用户投诉产生的模板 denylist 按用户隔离。

- 数据库与审计：
  - 新增 Alembic `0008_never_repeat`：扩展 `question_fingerprint`，增加 `prompt_embedding`、`summary_embedding`、`decision_embedding`、`answer_skeleton_hash`、`dedupe_decision_json`；vector 维度固定为当前配置基线 `1024`。
  - 新增 `question_dedupe_check`，保存每次候选查重的输入摘要、命中层级、相似题、最高相似度、结构变化数量、最终 PASS/REJECT 和原因；被拒候选也留审计记录。
  - 新增 `question_template_denylist` 和 `question_duplicate_complaint`，记录用户重复投诉、相似历史题可选引用、重复类型、禁用的模板家族和触发题。
  - `question.status` 仍使用既有状态；重复投诉将当前 `question` 标记 `INVALID`，对应 `evaluation_report` 标记 `INVALID` 并清空/排除计分影响，相关 `defect_occurrence` 标记 `EXCLUDED` 后重算 profile。

- API、前端与任务链路：
  - 新增 `POST /api/v1/trainings/{session_id}/duplicate-complaints`：仅允许当前用户对已完成、已绑定正式题的 session 提交；请求包含 `reason`、可选 `similar_question_id`、可选 `duplicate_type`。
  - 响应返回 complaint id、question id、template family、处理状态和补题 job id；接口成功后排队 `PREPARE_QUESTIONS`，但不强迫用户当天再答。
  - `POST /api/v1/trainings/current` 继续只分配通过 P09 查重且未被 denylist 命中的 READY 题；已有 READY 题若命中用户模板 denylist，应在领取前作废/跳过。
  - 前端在完成训练并展示 provenance 后增加最小“标记换皮”入口，提交重复投诉并显示已作废状态；训练前仍不得暴露来源、目标缺陷或查重信息。
  - Worker 的 `PREPARE_QUESTIONS` 路径传入 `bundle.embedding`；所有现有 P08 测试构造同步更新为 mock embedding。

## 测试计划

- 后端规则与 Golden：
  - 新增 `tests/golden_cases/p09_dedupe_cases.json`，覆盖原题、标点差异、数字换皮、角色换皮、同事件、结构/答案骨架重复，以及应放行的远场景样本。
  - 单测规范化哈希、结构维度变化、普通/高频缺陷阈值、同事件永久退役、denylist 命中和 LLM 终审失败关闭。
- 后端集成与迁移：
  - Service 集成测试使用可控 embedding provider，验证已知换皮回归集全部拒绝，非重复候选进入 READY，灰区调用 LLM 终审并记录 model_run/dedupe_check。
  - API/DB 测试验证重复投诉：题作废、report 不计分、occurrence 排除、profile 重算、模板家族禁用、补题 job 入队、跨用户不可投诉/不可读。
  - Alembic 验证 `upgrade head -> downgrade 0007_source_question -> upgrade head`，检查 vector 列、新表、唯一约束、FK 和索引。
- 前端：
  - `apps/web/src/api/training.test.ts` 覆盖重复投诉 API 请求与响应。
  - 训练完成后 provenance 区域能提交投诉；按钮状态不会影响录音、上传、转写、来源展示的既有路径。
- MuMu 强制验收：
  - 使用 MuMu 12 ADB `127.0.0.1:16384`，通过 `adb reverse` 暴露本地 API/Web，使用非敏感测试账号。
  - 启动本地后端、worker、前端 dev server，配置测试库、`AI_PROVIDER_MODE=mock`、`SEARCH_PROVIDER=mock`、mock embedding；在 MuMu 浏览器/PWA 完成登录、录音、上传、追问、最终答、评审完成、来源展示、重复投诉提交。
  - 记录 MuMu 设备地址、访问 URL、测试账号、session id、complaint id、question/template family、DB/API 验证结果；若 MuMu 无法连接或录音路径无法完成，本任务验收阻塞。
- 必跑命令：
  - 后端：`uv lock --check`、`uv run python scripts/verify_dependency_policy.py`、`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app`、`uv run pytest -q`。
  - 前端：`pnpm --dir apps/web lint`、`pnpm --dir apps/web type-check`、`pnpm --dir apps/web test`、`pnpm --dir apps/web build`。
  - 数据库：P09 Alembic upgrade/downgrade/upgrade。
  - 完成后执行独立 `/review`，高/中优先级问题必须处理或明确记录。

## Done When 映射

- 已知换皮回归集全部拦截：由 P09 Golden、domain 单测、service 集成测试和 dedupe_check 记录证明。
- 同缺陷复测至少改变规定场景维度：由结构指纹比较测试证明普通复测 `>=4`、高频/高优先缺陷 `>=6`，人名、数字、公司名不计变化。
- 用户重复投诉永久影响后续候选过滤：由 duplicate complaint API/DB 测试和 MuMu 端到端验收证明题作废、不计分、模板家族 denylist 生效、后续 READY 题不再命中该家族。
- P0 边界保持：用户仍不能选择题型/缺陷/领域/难度；无合格来源或查重失败时不投放；所有模型与 embedding 通过 Provider；不新增生产依赖。

## 假设与停止条件

- 假设“MuMu 真机测试”指沿用仓库既有 MuMu 12 Android 验收方式；若必须改为物理 Android/iPhone，需要另行调整验收环境。
- 假设 P09 包含最小前端重复投诉入口，因为任务要求“用户标记重复”且 MuMu 验收需要可操作路径。
- 真实 Qwen/Embedding live smoke 不作为默认 Done 条件；只有用户后续显式提供环境变量并授权时才运行，未运行需如实报告。
- 若实现中发现需要新增生产依赖、改变公开训练流程语义、读取真实密钥/音频、或跨用户向模型发送私人回答内容，立即停止并重新确认范围。
