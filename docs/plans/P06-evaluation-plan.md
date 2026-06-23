# P06 严格证据化评审实施计划

Status: APPROVED
Approval date: 2026-06-23

## 摘要

- 业务结果：在 P05 已 VERIFIED 后，实现一次语音答辩的逻辑、口语、追问应变三类独立评审，并确保所有负面评价都有 `quote + start/end + confidence + missing_information + correction_rule`。
- 当前事实：P04 已 VERIFIED，P05/P06 仍是 NOT_STARTED；`services/backend/app/graphs/` 目前还没有实际 LangGraph 实现；本机存在 MuMu 相关目录，但 `adb` 不在 PATH，常见 MuMu 目录下暂未找到 `adb.exe`。
- 入口条件：先完成 P05，并在 P06 实施前确认 MuMu 可启动、可通过 ADB 或可观察方式访问本地开发服务；如果无法连接 MuMu，则 P06 验收阻塞，不能跳过。
- 用户决策：不论前端是否改动，P06 必须使用 MuMu 做实机/模拟器验收；不把 P03-P05 的既有验证记录作为 P06 的替代证据。
- 不包含：P07 缺陷画像累计、P08 真实来源/正式题库、申诉流程、50 条人工校准 Golden Set。

## 关键变更

- 数据库新增 P06 迁移，创建最小评审闭环表：`question_rubric`、`evaluation_report`、`evaluation_issue`、`prompt_version`、`model_run`。
- `question_rubric` 绑定 `training_session_id`，保留可空 `question_id`，保存 `version`、`dimensions_json`、`expected_elements_json`、`fatal_omissions_json`、`content_hash`、`frozen_at`，为 P08 正式题库兼容。
- `evaluation_issue` 绑定 `report_id`、`attempt_id`，尽量绑定 `transcript_segment_id`，保存 `category`、`code`、`severity`、`confidence`、`quote`、`start_ms`、`end_ms`、`explanation`、`missing_information`、`correction_rule`、`verification_json`。
- 新增 Pydantic Schema：`AnswerStructure`、`LogicIssue`、`LogicReview`、`EvidenceVerification`，并补充内部 `SpeechReview`、`AdaptabilityReview`、`EvaluationResult`，保证三类评分独立。
- 新增版本化 Prompt：`answer_structure`、`logic_review`、`adaptability_review`、`evidence_verification`；只输出结构化结论和可审计证据，不要求隐藏思维链。
- 新增确定性评分模块，例如 `app/domain/scoring.py`：模型只给候选判断，Python 负责维度权重、硬封顶、最终分数和失败关闭。
- 新增评审服务/图节点：冻结 rubric、结构提取、逻辑初评、口语统计、应变评审、证据复核、应用封顶、持久化报告；接入 P05 的 `EVALUATING -> COMPLETED/INVALID/FAILED_RETRYABLE` 流程。
- 评审走 worker/job，不让 API 长时间阻塞；AI 调用通过现有 Provider Protocol 的 `review`/`verify` slot，记录 `model_run`，不新增生产依赖。

## 接口与默认规则

- 新增 `EVALUATE_SESSION` job，idempotency key 使用 `evaluate_session:{session_id}`。
- 默认 P06 开发 rubric 使用固定权重：逻辑 60%、口语 20%、应变 20%；硬封顶优先于加权总分，三类原始分始终单独保存。
- 默认 confidence 使用 `low | medium | high`；“未表达”和“明确错误”必须分开，禁止推断人格、智商、音色、口音、情绪或领导力气质。
- 除非 P05/P06 实施时已有报告 API 约定，否则只新增后端内部/测试读取能力，不扩展正式前端报告页。
- MuMu 验收必须覆盖 P03-P06 的用户路径：录音、上传、转写状态、P05 追问/最终答、P06 评审完成和负面 issue 时间点证据。

## 实施步骤

1. 实施前确认工作区仍干净，并切到任务分支 `codex/p06-evaluation`。
2. 确认 P05 已 VERIFIED，读取 P05 交接文档和实际 `TrainingState`、图节点、worker/job 接口；如 P05 尚未完成，停止实施。
3. 定位 MuMu 启动方式和 ADB 或可观察连接方式；确认 MuMu 浏览器能访问本地前后端服务；如果不能连接，先解决环境问题。
4. 增加 P06 数据库模型、Alembic 迁移和 repository 方法，先覆盖迁移回滚、幂等 report/issue 写入和用户隔离查询。
5. 增加评审 Pydantic Schema、Prompt 文件和开发 Golden fixtures，确保结构化输出不包含隐藏思维链或不可审计推断。
6. 编写 quote/时间戳证据复核和评分封顶单元测试，再实现纯 domain 规则。
7. 实现评审服务：读取已成功转写的 FIRST/FOLLOWUP/FINAL attempt，调用 review/verify provider，保存 `model_run` 和验证后的 issue。
8. 接入 P05 图和 worker：最终答完成后幂等创建 `EVALUATE_SESSION` job，评审成功后推进 session，失败时进入可重试或 INVALID 状态。
9. 补齐后端、Golden、迁移、图/worker 测试；最后启动本地服务并用 MuMu 跑一次强制端到端验收。
10. 执行独立 `/review`，修复高/中优先级问题或在完成报告中明确记录。

## 验证计划

- 后端单元测试：quote 为空会被拒绝；quote 不存在于校正版转写会被拒绝；时间点必须落在 transcript segment 内；跨 segment quote 能映射到有效区间；硬封顶覆盖“答非所问但语言流畅”。
- 服务/集成测试：Mock LLM 返回结构化 `AnswerStructure/LogicReview/EvidenceVerification` 后生成报告；无效证据不落入最终 issue；重复运行同一 session 不重复创建 report/issue/model_run。
- 图/worker 测试：P05 最终答后进入评审；成功后 session 完成；Provider/schema 失败进入可重试失败或 INVALID，不生成伪造报告。
- 数据库测试：Alembic `upgrade head`、`downgrade -1`、再次 `upgrade head`；验证 FK、唯一约束和 user_id 隔离查询。
- Golden Case：创建开发回归集，至少覆盖无 quote、quote 不匹配、时间戳边界、答非所问封顶、框架空泛封顶、追问后有效修正、高质量无负面问题。
- 必跑后端命令：
  - `cd services/backend && uv run ruff check .`
  - `cd services/backend && uv run ruff format --check .`
  - `cd services/backend && uv run mypy app`
  - `cd services/backend && uv run pytest -q`
  - `cd services/backend && uv run python scripts/verify_dependency_policy.py`
  - `cd services/backend && uv lock --check`
- 强制 MuMu 验收：
  - 启动后端、worker、前端 dev server。
  - 在 MuMu 浏览器访问局域网或宿主机地址。
  - 完成一次非敏感中文测试录音的第一答、追问答、最终答。
  - 确认后端生成评审报告，所有负面 issue 有可定位时间点。
  - 记录 MuMu 启动/连接方式、访问 URL、测试账号/非敏感样例说明、录音上传成功、转写成功、评审完成、至少一条 issue 的 `quote/start/end` 与音频片段可回放定位。

## 假设、风险与停止条件

- 假设：P06 按“P05 后实施”实施，不抢跑完整图闭环。
- 假设：P06 只做开发 Golden 回归集；SOP 的 50 条人工标注 Golden Set 留作生产校准或后续任务。
- 风险：MuMu 环境当前只发现安装目录，未发现 `adb.exe`；实施阶段若仍找不到 MuMu 可执行文件或 ADB 连接方式，必须先解决环境问题，不得把桌面浏览器测试替代 MuMu。
- 风险：真实模型 smoke 默认不运行，除非用户另行授权并设置 `RUN_LIVE_AI_TESTS=1`；MuMu 录音使用非敏感测试内容。
- 停止条件：P05 未 VERIFIED、工作区出现无关未提交改动、需要读取真实 `.env`/生产音频、需要新增生产依赖、需要改变 P0 产品规则或跨入 P07/P08 范围。
- 回滚：revert P06 代码，执行 Alembic `downgrade -1` 移除 P06 表，暂停或删除未处理的 `EVALUATE_SESSION` job；无依赖或锁文件回滚需求。
