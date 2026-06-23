# P07 个人缺陷经验库与训练画像计划

Status: APPROVED
Approval date: 2026-06-23

## 摘要

- 业务结果：把 P06 已证据复核的 `evaluation_issue` 幂等沉淀为用户长期缺陷画像，并提供后端 API 查询画像、历史证据和发起评审/分类申诉。
- 当前事实：工作区干净；当前迁移头是 `0005_evaluation`；P06 已有 `evaluation_report/evaluation_issue`，但还没有 P07 的画像表、申诉表或 `/me/defects` API。
- 已锁定范围：只做后端 API；历史相似匹配采用确定性 MVP；申诉只覆盖评审误解/缺陷分类错误。
- 用户补充验收要求：P07 必须使用 MuMu 模拟器做实机路径测试，不能只用桌面浏览器或后端测试替代。
- 不包含：前端页面、embedding+LLM 根因终审、正式题库/来源、防重复、周报、申诉后台处理 UI。

## 关键变更

- 新增 P07 迁移 `0006_defect_memory`，创建 `defect_definition`、`defect_occurrence`、`defect_evidence`、`defect_profile`、`appeal`。
- `defect_definition` 按 SPEC 7.1 初始化稳定缺陷字典；P06 历史短码通过确定性 alias 归一到 SPEC 编码，例如 `NO_DECISION -> STRUCT-01`、`ASSUMPTION_AS_FACT -> INFO-01`、`SINGLE_OPTION -> DEC-01`、`GENERIC_FRAMEWORK -> STRUCT-04`。
- 新增缺陷画像 domain/service/repository：从 `COMPLETED` report 中读取 verified issue，低置信度 occurrence 记为 `PENDING` 且不计入画像；`medium/high` 记为 `ACTIVE` 并参与 profile 重算。
- Profile 状态规则：
  - `observed`：有 active occurrence，但未满足确认条件。
  - `confirmed`：同一缺陷 active occurrence 至少 3 次、跨至少 2 个 `scenario_key`，且至少 2 次来自 `FIRST` 阶段。
  - `high-priority`：confirmed 后满足严重度高、频率高或改善/稳定后复发。
  - `improving/stable-improved`：本阶段支持存储、API 返回和复发回退；自动进入改善状态等待后续有“目标缺陷干净复测”数据源后接入。
- `scenario_key` 最小规则：优先使用 `training_session.question_id` 形成 `question:{id}`；没有 question 时使用 `unscoped`，避免把当前开发测试题误判为跨场景。
- `EvaluationService.evaluate_session()` 在新生成或复用已完成 report 时调用 P07 同步服务；同步必须可重复运行，不重复创建 occurrence/evidence/profile。

## API 与接口

- 新增 `GET /api/v1/me/defects`：
  返回当前用户 profile 列表，包含 `code/name/description/state/severity/frequency/recurrence/priority/confidence/active_occurrence_count/suspended_occurrence_count/last_seen_at`。
- 新增 `GET /api/v1/me/defects/{code}/occurrences`：
  只返回当前用户该 defect 的历史证据，包含 occurrence 状态、session、attempt stage、quote、start/end、severity、confidence、explanation、missing_information、correction_rule、`similarity_reasons`。
- 新增 `POST /api/v1/trainings/{id}/appeals`：
  payload 为 `type: "evaluation" | "defect_classification"`、`reason`、可选 `issue_id`、可选 `defect_code`；创建 `OPEN` appeal 后将命中的 occurrence 标记为 `SUSPENDED` 并重算 profile。
- 内部 repository/service 提供 appeal 复核方法：
  `REVIEWED_ACCEPTED` 时 occurrence 永久 `EXCLUDED`；`REVIEWED_REJECTED` 时恢复为原 `ACTIVE/PENDING` 并重算。P07 不新增后台复核 API。
- 主要影响模块：数据库模型/迁移、`services/backend/app/domain`、`services/backend/app/repositories`、`services/backend/app/services`、`services/backend/app/api/v1/me.py` 与训练路由。

## 测试与验收

- Domain 单元测试：状态转换、优先级计算、alias 归一、低置信度 pending、不满足 3 次/2 场景不 confirmed、改善/稳定状态收到新 occurrence 后回退 high-priority。
- Repository/service 集成测试：同一 report 同步两次 occurrence 不重复；3 次/2 场景后 confirmed；严重度/频率触发 high-priority；申诉后 suspended occurrence 不再影响 profile；复核 rejected/accepted 分别恢复或排除。
- API 测试：两个用户互不可见；`GET /me/defects` 和 occurrence 详情只返回本人数据；`POST /trainings/{id}/appeals` 只能操作本人 session/issue。
- 迁移测试：Alembic `upgrade head`、`downgrade 0005_evaluation`、再次 `upgrade head`；验证 P07 表和关键唯一约束。
- MuMu 实机验收必须执行：
  - 启动本地后端、worker、前端 dev server，并通过 `adb reverse` 或可验证网络方式让 MuMu 访问本地服务。
  - 在 MuMu 浏览器/PWA 中使用非敏感测试账号完成一次训练路径：登录、创建训练、录音上传、转写、P05 追问/最终答、P06 评审完成。
  - 使用该 MuMu 生成的真实 session 验证 P07 同步：后端出现 occurrence/profile；`GET /api/v1/me/defects` 返回画像；`GET /api/v1/me/defects/{code}/occurrences` 返回 quote/time 证据；发起评审/分类申诉后 profile 重算排除 suspended occurrence。
  - 记录 MuMu 设备地址、访问 URL、测试账号标识、session id、关键 API/数据库验证结果；不得用桌面浏览器测试替代。
- 必跑命令：
  - `cd services/backend && uv run ruff check .`
  - `cd services/backend && uv run ruff format --check .`
  - `cd services/backend && uv run mypy app`
  - `cd services/backend && uv run pytest -q`
  - `cd services/backend && uv lock --check`
  - 如触发 schema/rule golden：运行 P06/P07 相关 golden 回归
- P07 不改前端；因此前端 lint/type/test/build 仅在实际修改 `apps/web/` 时必跑，但 MuMu 实机路径测试始终必跑。

## Done When 映射

- 同一问题幂等累计：由 `UNIQUE(session_id, issue_id, defect_code)`、同步服务重复运行测试和 MuMu session 二次同步验证证明。
- 画像区分五种状态：API/schema 支持全部状态；P07 自动覆盖 observed/confirmed/high-priority 和复发回退；improving/stable-improved 作为持久状态和返回状态保留。
- 申诉后不继续影响画像：`OPEN` appeal 将相关 occurrence 置为 `SUSPENDED`，profile 重算排除 suspended/excluded，复核后按结果恢复或永久排除。
- 实机验收：MuMu 完整路径必须产生可追踪 session，并证明 P07 API 能读取和暂停该 session 的缺陷证据。

## 假设与停止条件

- 假设 P07 基于 P06 已落地的 `evaluation_issue`；若执行分支缺少 P06 迁移或表结构，先停止。
- 假设本阶段不新增生产依赖，不调用真实模型，不读取 `.env`，不实现 embedding/LLM 历史根因终审。
- 如果 MuMu 无法启动、无法连接本地服务或无法完成录音/上传路径，P07 验收阻塞，不能用桌面浏览器替代。
- 若必须让 `improving/stable-improved` 从真实正向复测自动产生，需要新增目标缺陷复测数据源，应停止并重新确认范围。
- 若需要前端展示、后台复核 UI、四类完整申诉或 P08/P09 题库/查重能力，应作为后续任务处理。
- 回滚方式：revert P07 代码并执行 Alembic downgrade 到 `0005_evaluation`；由于不新增依赖，无锁文件回滚预期。
