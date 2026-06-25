# P10 自适应随机突击与推送计划

Status: APPROVED
Approval date: 2026-06-24

## 验收口径变更

2026-06-24 用户明确要求“不用 MuMu 模拟器测试了，使用 APP，先忽略 MuMu 模拟器的验证”。因此 P10 完成验收以已 USB 连接的物理手机 vivo X100 Pro + Chrome PWA/App 链路为准；MuMu 正向 Web Push 问题保留为后续兼容风险，不再阻塞本任务。

## 摘要

- 目标：把当前“用户主动创建训练并立即曝光题目”的流程，改成系统按个人缺陷画像和 READY 库存，在允许窗口内随机发起中性 Web Push；用户接受后才曝光题目并进入既有语音答辩闭环。
- 用户可见结果：用户只能设置时间/隐私/通知边界，不能选择题型、缺陷、领域、难度；通知只显示“突击审核已到达”和预计用时；漏接、过期、通知失败不评分；看题后退出则题目永久退役。
- 当前事实：P09 已 VERIFIED；`apscheduler==3.11.2`、`pywebpush==2.3.0` 和 VAPID 配置项已存在；`scheduler` 进程目前是占位；`training_session` 已有 P10 所需核心阶段枚举但缺少通知、接受、延期和决策审计字段。
- 明确不做：不新增生产依赖，不读取真实 `.env`，不引入本地模型/GPU，不做 P11 发布验收/周报/数据删除，不允许用户选择训练方向。

## 关键变更

- 后端调度与规则：
  - 新增随机突击 domain/service：按 `user_training_policy` 的窗口、勿扰、时区、`daily_max` 生成非固定候选时间；按缺陷优先级、55/25/10/10 配额、连续同缺陷疲劳惩罚和 READY 库存选择候选，并保存 `delivery_decision_json`。
  - Scheduler 每分钟处理到期突击和过期通知；每日或库存低于阈值时补充 READY 题。READY 目标为每用户 7 道，低于 3 道高优先补题；库存不足时降低突击频率，不投放 DRAFT/未查重/无来源题。
  - 题目在通知前不曝光；未接受/通知失败/过期时不创建 attempt、不评分，题目可重新进入未曝光 READY 池；接受后立即标记曝光，`question.exposed_count=1`，后续退出为 `ABANDONED` 且题目不再复用。

- API 与状态流：
  - 新增 `GET /api/v1/push/public-key`、`POST /api/v1/push/subscriptions`，保存用户 Web Push 订阅；失效订阅由后端标记 inactive。
  - 将训练入口调整为 `GET /api/v1/trainings/current`：只返回用户当前可见的 `NOTIFIED` 或已接受/进行中 session，不返回未来 `SCHEDULED`，避免提前暴露突击存在和方向。
  - 新增 `POST /api/v1/trainings/{id}/accept`：仅允许 owner 在通知未过期时接受，原子转入 `WAIT_FIRST_AUDIO` 并曝光题目；既有 attempts/upload/resume/Graph 流程保持不变。
  - 新增 `POST /api/v1/trainings/{id}/defer`：仅允许通知未过期且未曝光时延期一次，重新随机安排到下一个允许窗口；不曝光、不计分。
  - 新增 `POST /api/v1/trainings/{id}/abandon`：仅用于已曝光未完成 session，标记 `ABANDONED`，不进入评审/缺陷画像。

- 数据库与配置：
  - 新增 Alembic `0009_random_strike`：创建 `push_subscription`；扩展 `training_session` 的 `notified_at`、`notification_expires_at`、`accepted_at`、`delivery_decision_json`、`deferred_count`、`push_status`、`push_error_code`；增加用户活跃 session、到期调度、订阅查询索引。
  - 保持现有 VAPID 环境变量；新增 `validate_push()` 只校验推送所需公私钥，不打印密钥。MuMu 验收使用临时非生产 VAPID keypair。
  - 不新增或升级依赖，不刷新锁文件；若实现发现必须改依赖，停止并重新确认。

- 前端 PWA：
  - 注册 Service Worker 与 Push subscription，请求通知权限并提交订阅；通知 payload 只含中性文案和 session id，不含题型、缺陷、来源、难度或目标。
  - 首页改为“等待突击/有待接受突击/进行中训练”状态；用户点通知或打开 PWA 后查询 current，再选择接受或延期。
  - 题目文本、来源摘要和录音入口只在接受后显示；延期/过期/通知失败使用用户可理解状态，不触发录音或评分。
  - 为 MuMu 本地验收启用可测试的 PWA/Service Worker dev 配置；生产 build 行为保持 PWA 可安装。

## 测试计划

- 后端规则与 API：
  - 单测允许窗口、勿扰、跨午夜时间段、随机时间不固定、daily max、疲劳惩罚、连续两次同缺陷后强制插入其他能力、库存不足降频。
  - 集成测试覆盖：生成 `SCHEDULED`、发送/失败 Web Push、`NOTIFIED` 过期为 `EXPIRED`、延期一次、接受后才曝光、曝光后 abandon、通知失败/过期不产生 report/occurrence。
  - 跨用户测试：用户不能读取/接受/延期/abandon 他人的 session 或订阅；READY 选择继续遵守 P09 用户级 denylist。
  - 迁移测试：`upgrade head -> downgrade 0008_never_repeat -> upgrade head`，验证新表、列、索引、约束和回滚。

- 前端：
  - API 测试覆盖 push public key、subscription、current、accept、defer、abandon。
  - 组件/流程测试覆盖：通知权限拒绝、无 current、待接受、延期后隐藏题目、接受后才显示题目、过期/失败不允许录音、完成后 provenance/重复投诉不回退。
  - 必跑 `pnpm --dir apps/web lint`、`pnpm --dir apps/web type-check`、`pnpm --dir apps/web test`、`pnpm --dir apps/web build`。

- 原 MuMu 强制实机验收（已由上述验收口径变更取代）：
  - 使用 MuMu 12 Android 模拟器，沿用既有 ADB `127.0.0.1:16384`；通过 `adb reverse` 暴露本地 web/api，使用非敏感测试账号、mock AI/search/embedding 和临时测试库。
  - 在 MuMu 浏览器/PWA 中完成：登录、通知权限、Push 订阅、scheduler 生成并发送突击、系统通知到达、点击/打开 PWA、接受后题目才显示、录音上传、追问/最终答、评审完成。
  - 另跑 MuMu 负向验收：通知过期不评分、延期一次不曝光、通知失败或无订阅不评分、曝光后退出为 `ABANDONED` 且题目退役。
  - 记录设备地址、访问 URL、测试账号标识、session id、question id、push subscription id、delivery decision、DB/API 验证结果和截图目录。原计划中“若 MuMu 无法订阅或接收 Web Push，本任务验收阻塞”的条件已被 2026-06-24 用户批准变更：当前使用物理手机 PWA/App 实机证据完成 P10，MuMu 问题不再阻塞。

- 必跑命令：
  - 后端：`uv lock --check`、`uv run python scripts/verify_dependency_policy.py`、`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app`、`uv run pytest -q`。
  - 完成后执行一次独立 `/review`；高/中优先级问题必须修复或明确记录。

## Done When 映射

- 用户无法预知训练方向：由 current 不返回未来 `SCHEDULED`、通知中性文案、前端接受前隐藏题目/来源/缺陷、API/前端测试和物理手机 PWA/App 验收证明。
- 题目曝光后永久退役：由 accept/expose 原子更新、`question.exposed_count=1`、abandon/完成后不可再次领取的 DB/API 测试和物理手机 PWA/App 验收证明。
- 未接收、过期和设备通知失败不进入能力评分：由 EXPIRED/push failure 集成测试、无 attempt/report/occurrence 断言和自动化负向验收证明。
- P10 调度与库存可靠：由 scheduler/service 测试证明允许窗口随机、daily max、生效的疲劳系数、READY 库存阈值和补题 job 幂等。

## 假设与停止条件

- 原假设“MuMu 模拟器做实机测试”已由用户在 2026-06-24 明确变更为使用已连接物理手机 App/PWA 验收，并先忽略 MuMu 验证。
- 假设延期只允许在题目曝光前使用一次；曝光后不能延期，只能继续答题或 abandon。
- 默认不运行真实 Qwen/ASR/Embedding live smoke；P10 MuMu 验收使用 mock provider 验证产品和数据闭环。
- 若需要新增生产依赖、改变 P0 产品边界、读取真实 `.env`/生产数据/真实音频，立即停止并报告；MuMu Web Push 环境不可用仅记录为非阻塞风险。
