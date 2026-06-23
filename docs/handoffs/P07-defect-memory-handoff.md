# P07 个人缺陷经验库与训练画像交接

## 状态

- 交接状态：VERIFIED。
- 分支：当前 worktree 为 detached `HEAD`。
- 提交与合并状态：未提交；未执行 commit、push、merge、release。
- 阻塞项：无。已按用户提供的 code review 指南完成未提交变更审查；发现的 MEDIUM/P2 复发幂等问题已修复，并经 `$project-verify` 重新验证通过。

## 业务结果

- P06 的 `evaluation_issue` 现在会被幂等沉淀为长期缺陷 occurrence、证据和个人 profile。
- 同一缺陷必须至少 3 次 active occurrence、跨至少 2 个 `scenario_key`，且至少 2 次来自 `FIRST` 阶段，才会从 `observed` 进入稳定确认状态。
- 低置信度 issue 只进入 `PENDING` occurrence，不计入 profile 权重。
- 申诉会把命中的 `ACTIVE/PENDING` occurrence 暂停为 `SUSPENDED`，profile 重算时排除；复核 accepted 后永久 `EXCLUDED`，rejected 后恢复原状态。
- 当前阶段支持 `observed`、`confirmed`、`high-priority`、`improving`、`stable-improved` 的存储和 API 返回；`improving/stable-improved` 的自动进入等待后续目标缺陷复测数据源。

## 主要实现范围

- Database：新增 Alembic 迁移 `0006_defect_memory.py`，创建 `defect_definition`、`defect_occurrence`、`defect_evidence`、`defect_profile`、`appeal`，并按 SPEC 7.1 初始化 34 个缺陷定义。
- Domain：新增 `app/domain/defects.py`，实现缺陷短码归一、低置信度 pending、确认阈值、优先级计算、纠正后复发回退 high-priority、改善状态保留。
- Repository/Service：新增 `app/repositories/defects.py` 与 `app/services/defects.py`，从 completed report 同步 issue，保证 `(session_id, issue_id, defect_code)` 幂等，并提供 profile/occurrence 查询和 appeal 创建/复核。
- API：新增 `GET /api/v1/me/defects`、`GET /api/v1/me/defects/{code}/occurrences`、`POST /api/v1/trainings/{id}/appeals`。
- P06 集成：`EvaluationService.evaluate_session()` 在新生成或复用 completed report 时调用 P07 同步。
- Tests：新增 P07 domain、repository/API、migration 测试，并覆盖申诉 accepted/rejected 两条复核路径，以及改善后复发 high-priority 重复重算幂等回归。

## Review 与修复结果

- 本地 diff review 发现申诉 payload 可在无 `issue_id` 且无 `defect_code` 时创建空靶标申诉；已修复为 API 层 422，并补充回归测试。
- 本地 diff review 发现内部 appeal 复核方法允许已复核申诉被二次调用翻转结果；已修复为非 `OPEN` 申诉直接返回，并补充 accepted 后二次 rejected 不翻转的回归测试。
- 本地 diff review 发现 P07 同步读取 `EvaluationIssue.attempt_id` 时未显式约束 attempt 属于同一 training session；已收紧 join 条件，并补充跨 session attempt 被忽略的回归测试。
- 用户按 code review 指南发起最终审查后，发现 MEDIUM/P2：`stable-improved` 后复发第一次进入 `high-priority`，但同一 occurrence 重复 rebuild 会掉回 `observed`。根因是 domain 规则只看 `previous_state`，没有持久保留 `recurrence`。已将既有 profile recurrence 作为规则输入传回，并新增 domain + repository/service 回归测试；`$project-verify` 复发幂等探针通过。

## 验收证据

- `cd services/backend && uv run ruff check .`：通过，`All checks passed!`
- `cd services/backend && uv run ruff format --check .`：通过，`82 files already formatted`
- `cd services/backend && uv run mypy app`：通过，`Success: no issues found in 62 source files`；保留既有 unused section 提示。
- `cd services/backend && uv lock --check`：通过。
- `cd services/backend && TEST_DATABASE_URL=postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking_test TEST_DATABASE_SYNC_URL=postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test uv run pytest -q`：通过，`88 passed`；保留既有 Starlette/httpx 与 Alembic `path_separator` warnings。
- `cd services/backend && TEST_DATABASE_URL=postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking_test TEST_DATABASE_SYNC_URL=postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test uv run pytest tests/test_defect_memory_p07.py tests/test_migrations_p07.py -q`：通过，`9 passed`，P07 repository/API 与 Alembic upgrade/downgrade/upgrade 均通过。
- `cd services/backend && uv run pytest tests/test_defect_rules_p07.py -q`：通过，`8 passed`，覆盖状态转换、确认阈值、复发和改善状态保留。
- `cd services/backend && TEST_DATABASE_URL=postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking_test TEST_DATABASE_SYNC_URL=postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test uv run pytest tests/test_evaluation_p06.py tests/test_evaluation_rules_p06.py -q`：通过，`12 passed`。
- `cd services/backend && uv run python -` 复发幂等探针：通过；第一次和第二次重算均保持 `high-priority`，`recurrence == 1`。
- `cd services/backend && uv run python scripts\verify_dependency_policy.py`：通过。
- `RUN_LIVE_AI_TESTS=1` dev env live smoke：通过 Qwen、Embedding、TTS；随后生成非敏感英文 MP3 并通过临时 HTTPS 直链执行 FunASR smoke，返回 1 个 segment，transcript 为 `This is an ASR live smoke test for the Thinking Coach project.`
- `git diff --check`：通过。

## MuMu 实机验收

- 设备：MuMu 12 ADB `127.0.0.1:16384`。
- 本地访问：`adb reverse tcp:8010 tcp:8010`、`adb reverse tcp:5182 tcp:5182`；MuMu 浏览器访问 `http://127.0.0.1:5182/`。
- 测试账号：`mumu-p07`，非敏感本地测试账号。
- 后端配置：本地测试库 `thinking_test`，`AI_PROVIDER_MODE=mock`，临时音频目录 `C:\Users\WJ\AppData\Local\Temp\thinking-coach-p07-mumu\audio`。
- 端到端路径：在 MuMu 中完成登录、第一答录音、追问答录音、最终答录音、转写、`GRAPH_RESUME`、`EVALUATE_SESSION`、报告完成。
- MuMu session：`873caf7e-4a31-4e88-b375-9fa34f7993ed`，状态 `COMPLETED`。
- MuMu report：`68b075f8-5da0-49c0-9dd4-17d10ba276e5`，状态 `COMPLETED`，final score `90`。
- 受 P06 mock evaluator 限制，本轮自然评审没有产生负面 issue；为验证 P07，同一 MuMu session 上插入 controlled `EvaluationIssue` `a3e5b20f-58ef-4b71-a963-f54d0b90a1da`，code `ALIGN-01`、severity `4`、confidence `high`、quote `mock transcript`，然后调用 P07 同步。
- P07 API 证据：`GET /api/v1/me/defects` 返回 `ALIGN-01` profile，state `observed`，active `1`；`GET /api/v1/me/defects/ALIGN-01/occurrences` 返回该 MuMu session 的 quote/time 证据；`POST /api/v1/trainings/873caf7e-4a31-4e88-b375-9fa34f7993ed/appeals` 创建 OPEN appeal `2cac4867-c5ae-4e8b-ad53-347657c5dc87` 后，profile active `0`、suspended `1`。
- 验收结束后本次 API/Web/worker 进程已停止，`tcp:8010` 与 `tcp:5182` reverse 已移除；保留了 unrelated `tcp:4173` reverse。

## Done When 映射

- 同一问题幂等累计：通过。唯一约束、重复同步测试、repository/API 测试和复发 high-priority 重复重算探针均覆盖。
- 画像区分五种状态：通过。API/schema 支持五状态；自动规则覆盖 `observed/confirmed/high-priority` 和改善后复发；`improving/stable-improved` 作为持久状态保留并有 domain 测试。自动进入改善状态不在 P07 批准范围内。
- 申诉后相关 occurrence 不继续影响画像，直到复核：通过。创建申诉后 profile 排除 suspended；复核 accepted 永久 excluded，rejected 恢复原状态。
- MuMu 实机验收：通过。完成 MuMu 用户路径，并在同一 session 上验证 P07 profile、occurrence 证据和申诉暂停。

## 未完成与不适用项

- 未改前端页面：P07 批准范围为后端 API；MuMu 使用既有训练 UI 走实机路径。
- 未运行前端 lint/type/test/build：未修改 `apps/web/` 源码；本次只执行了 `pnpm install --offline --frozen-lockfile` 以恢复本地 `node_modules`，未改变锁文件。
- 真实线上模型 smoke：已在 `RUN_LIVE_AI_TESTS=1` 下使用 `.env.example` 非敏感默认值加 dev env 覆盖执行 Qwen、Embedding、TTS smoke；ASR 使用生成的非敏感英文 MP3 和临时 HTTPS 直链通过 FunASR smoke。
- 未实现重复题、来源错误、转写错误的完整申诉分支；本阶段只覆盖评审误解和缺陷分类错误。

## API、数据库、配置、依赖影响

- API：新增个人缺陷画像、缺陷历史证据和训练申诉创建接口。
- 数据库：新增 P07 五张表；可 downgrade 到 `0005_evaluation` 并再次 upgrade。
- 配置：未新增环境变量。
- 依赖：未新增或升级生产依赖；`uv.lock` 通过 `--check`，`pnpm-lock.yaml` 未修改。
- 隐私：所有 profile、occurrence、appeal 查询与写入都以当前 `user_id` 或 owned session/issue 校验为边界。

## 已知风险

- MuMu 验收使用 mock STT/LLM；本轮额外通过 Qwen、Embedding、TTS、FunASR live smoke，但仍不能证明真实中文录音或端到端真实转写/评审质量。
- P06 mock evaluator 本轮没有自然负面 issue，因此 P07 profile 的实机 API 验证使用 controlled issue；后续接真实题源和更强 mock fixture 后，可减少这种人工控制步骤。
- 历史相似原因当前是确定性 MVP：同缺陷、同场景、相同 correction rule、missing information 交集；embedding/LLM 根因终审留给后续任务。
- `improving/stable-improved` 自动进入需要 P08-P10 后有目标缺陷复测与干净样本数据源；P07 只保证这两个持久状态可存储、返回，并在复发时稳定回退 high-priority。

## 下一任务建议

- 推荐进入 P08：来源与出题。
