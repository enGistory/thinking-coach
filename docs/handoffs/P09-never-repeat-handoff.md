# P09 永不重复与换皮拦截交接

## 状态

- 交接状态：VERIFIED。
- 分支：`codex/p09-never-repeat`。
- 提交与合并状态：未提交；未执行 commit、push、merge、release。
- 阻塞项：无。已完成 review -> fix -> verify 闭环；P09 验收为 PASS。

## 业务结果

- READY 题进入训练前经过规范化 hash、source_event、embedding、结构指纹、答案骨架和必要 LLM 终审去重。
- 已知原题、数字换皮、角色换皮、结构换皮和答案骨架重复会被拦截，并写入 `question_dedupe_check` 审计。
- 完成训练后，用户可在 provenance 区域提交 duplicate complaint；投诉 accepted 后当前题 `INVALID`，report `INVALID` 且分数清空，相关 defect occurrence `EXCLUDED` 并重算 profile。
- 模板 family 进入用户级 denylist；后续 READY 题领取前跳过或作废同 family，补题 job 入队且重复投诉幂等。
- P09 不实现 P10 随机突击/Web Push，不运行真实模型 live smoke 作为默认 Done。

## 主要实现范围

- Domain：`services/backend/app/domain/question_dedupe.py` 实现文本规范化、hash、余弦阈值、结构比较和答案骨架 hash。
- Prompts：`prompts/dedupe_adjudication/v1.0.0.system.md`、`prompts/dedupe_adjudication/v1.0.0.user.md`。
- Database：`services/backend/alembic/versions/0008_never_repeat.py` 扩展 `question_fingerprint`，新增 `question_dedupe_check`、`question_template_denylist`、`question_duplicate_complaint`，并在 P09 upgrade 移除全局 `normalized_hash` 唯一约束、downgrade 恢复。
- Repository/Service：`source_questions.py`、`question_duplicates.py`、`jobs.py`、`defects.py` 实现用户级历史、denylist、审计、作废和幂等补题。
- API：新增 `POST /api/v1/trainings/{session_id}/duplicate-complaints`。
- Worker：prepare questions 路径传入 embedding provider。
- Frontend：训练 API 与 `HomeView` 在 provenance 后新增重复投诉入口。
- Tests：新增 P09 golden、domain、service/API、migration、frontend API 测试；P08 相关测试同步 embedding provider。

## Review 与修复结果

- HIGH fixed：跨用户去重污染。根因是历史/hash 检查与全局 `normalized_hash` 唯一约束按系统全局生效。修复为用户级历史/hash 检查，并通过 P09 迁移移除全局唯一约束；已加回归测试。
- MEDIUM fixed：重复投诉在既有补题 job 已成功后仍可能再次创建 prepare job。修复为存在 complaint 时返回既有 prepare job，不重复副作用；已加回归测试。
- 未遗留 BLOCKER/HIGH/MEDIUM review 问题。

## 验收证据

- `uv lock --check`：通过。
- `uv run python scripts/verify_dependency_policy.py`：通过。
- `git diff --check`：通过。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：通过。
- `uv run mypy app`：通过，`Success: no issues found in 69 source files`。
- `uv run pytest tests/test_question_dedupe_rules_p09.py tests/test_never_repeat_p09.py tests/test_migrations_p09.py -q`：`8 passed`。
- `uv run pytest -q`：通过，1 个既有 skip，仅保留既有 Starlette/httpx 与 Alembic deprecation warnings。
- Alembic 临时库 `thinking_verify_p09_accept_142806`：`upgrade head -> downgrade 0007_source_question -> upgrade head`，最终版本 `0008_never_repeat (head)`。
- 前端 `pnpm lint`、`pnpm type-check`、`pnpm test`、`pnpm build`：全部通过；Vitest `6 files / 20 tests`。
- MuMu 12 ADB `127.0.0.1:16384`：登录、FIRST/FOLLOWUP/FINAL 录音、报告/provenance 展示、duplicate complaint 提交全部通过。
- MuMu 数据库证据：
  - 数据库：`thinking_mumu_p09_accept_20260624_142911`
  - session：`b23b54f1-3bab-4f71-bf45-e873fe3e4d01`
  - question：`ceba88fb-c091-442b-9eb4-80d8aabf6eb1` -> `INVALID`
  - report：`INVALID`，`final_score=None`
  - complaint：`c3d864f6-0f7d-4a91-873b-cd3668a01f6a` -> `ACCEPTED`
  - denylist：`5774996d-bdbd-4e2e-8d0a-794c6a502b75`
  - same-family READY count：`0`
  - replacement job：`f3be33a4-d7ab-4d7c-a080-27feb40c018b` -> `SUCCEEDED`
  - repeat POST：返回同一 complaint/job，`prepare_job_count=1`，`complaint_count=1`
- MuMu 截图与临时证据目录：`C:\Users\WJ\AppData\Local\Temp\thinking-coach-p09-accept-20260624_142911`。

## Done When 映射

- 已知换皮回归集全部拦截：通过，P09 golden/domain/service tests 与 dedupe check audit 覆盖。
- 同缺陷复测至少改变规定场景维度：通过，普通场景 >=4，高优先级场景 >=6 的结构维度测试覆盖。
- 用户重复投诉永久影响后续过滤：通过，MuMu 与 DB 证据显示 question/report 作废、分数清空、denylist 生效、无同 family READY 题、补题 job 幂等。
- P0 边界保持：通过，未给用户选择题型/缺陷/来源；未新增本地模型/GPU/生产依赖；保留 provider 边界；无合格来源或去重失败时 fail-closed。

## API、数据库、配置、依赖影响

- API：新增 `POST /api/v1/trainings/{session_id}/duplicate-complaints`。
- DB：新增 P09 migration 对象；`question_fingerprint.normalized_hash` 在 P09 后不再全局唯一，去重唯一性由用户级 repository 规则控制。
- Config：无新增环境变量。
- Dependencies：无新增或升级生产依赖；lock check 与依赖策略校验通过。
- Frontend：完成后 provenance 下新增重复投诉表单；未向前端暴露后端密钥。

## 已知风险

- MuMu 路径使用 mock STT/LLM，验证产品/UI/数据闭环，不等同真实模型质量验收。
- 真实 Qwen/Embedding live smoke 未运行；P09 计划明确 live smoke 默认不作为 Done 条件，除非后续授权环境。
- 既有 Starlette/httpx 与 Alembic `path_separator` deprecation warnings 仍存在。
- 临时验收库与截图保留为本地证据。
- 当前 worktree 仍未提交。

## 回滚

- 代码回滚：撤回 P09 在 backend、frontend、prompts、tests 与 docs 的变更。
- DB 回滚：Alembic 从 `0008_never_repeat` downgrade 到 `0007_source_question`；注意 P09 downgrade 会恢复全局 `normalized_hash` 唯一约束，若环境中已有跨用户相同 hash，需要先评估数据冲突。
- 运维回滚：停用 P09 duplicate complaint 入口/路由和补题路径；无新增外部服务或依赖需要移除。

## 未实现范围

- P10 随机突击、Web Push、通知窗口和发布验收。
- 真实模型质量验收与 live AI smoke。
- 重复投诉表单的完整 UX 打磨和本地化之外的增强。

## 下一任务建议

- 进入 P10 随机突击。
- 前置注意：保持 P09 READY 过滤与 denylist 行为；P10 scheduler/window randomness 不得在答题前暴露训练目标；提前确定 P10 是否要求 MuMu 推送/通知验收及对应环境。
