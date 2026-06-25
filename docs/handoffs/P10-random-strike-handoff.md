# P10 随机突击与推送交接

日期：2026-06-25
分支：`codex/p10-random-strike`
状态：`VERIFIED`（按 2026-06-24 用户明确变更后的物理手机 App/PWA 验收口径；MuMu 正向 Push 已批准先忽略并保留为非阻塞风险）

## 当前结果

P10 代码实现已完成并按用户最新验收口径通过。原计划中的 MuMu 正向 Push 路线仍被浏览器网页 Push API 接桥阻塞：Firefox/Fenix、AOSP Chromium、IronFox 和 Iceraven 都无法为 PWA 成功生成网页 `PushSubscription`。用户已于 2026-06-24 明确要求先忽略 MuMu 验证，改用已 USB 连接的物理手机 App/PWA 验收。物理手机 vivo X100 Pro + Chrome 在临时电脑代理后已经补齐正向实机链路：PWA 可生成真实 FCM `PushSubscription`，后端可通过真实 `PyWebPushSender` 发送到手机系统通知；打开 PWA 后接受突击，接受前不曝光题目，接受后题目 `EXPOSED/exposed_count=1`，并已在手机 Chrome 上完成首答、追问、最终答录音上传、mock 转写、mock 评审，session 到达 `COMPLETED`。

2026-06-25 最终 review/fix/verify 已完成：review 发现前端 `PushManager.subscribe()` reject 时会冒泡成泛化失败；已在 `setupPushNotifications()` 中把浏览器订阅注册失败受控降级为 `unsupported`，并新增回归测试覆盖 `Registration failed - push service error`。最终 `$project-verify` 重新跑过后端、P10 DB/API/迁移、前端 lint/type/test/build 与 `git diff --check`，结论为 PASS。

本轮追修已把 fake-IP DNS 问题从 smoke 脚本旁路改为默认关闭的正式配置：`WEB_PUSH_ALLOW_FAKE_IP_HOSTS` 只允许显式列出的 exact public host 在解析到 198.18.0.0/15 fake-IP 时继续发送；其他内网、回环、`.local`、非 443 endpoint 仍阻断。使用 `fcm.googleapis.com` allowlist 后，真实 `PyWebPushSender` 已无需 monkeypatch 即可发送到手机 Chrome。

验收口径变更与非阻塞风险：

- MuMu 仍没有可生成网页 `PushSubscription` 的浏览器环境；当前手机 Chrome 证据属于物理 Android 实机。该差异已由用户明确接受，不再阻塞 P10。
- Vivo/Chrome 通知栏中真实通知已到达；早期 ADB 只点标题/正文节点时出现过通知被消费但未唤起 Chrome。2026-06-24 追加补测解析 `expandableNotificationRow` 后确认是点位问题：点击整张 Chrome Web 通知行的中上部可唤起 Chrome；再用唯一 `click_probe` 参数证明通知 `data.url` 可落到目标 PWA URL。
- 手机 Chrome 在长链路测试中多次丢失 `sessionStorage` 登录态；已补前端 refresh token 静默恢复：登录成功后保存 refresh token，重新打开 PWA 时通过 `/api/v1/auth/refresh` 轮换出新的 access/refresh token，再恢复训练状态。完成态恢复兜底也已在 vivo X100 Pro + Chrome 上重跑确认：测试账号无当前会话时 `/trainings/current` 返回 404，通知 URL 中的 completed session 可恢复 `/state` 并显示完成页。

## 已实现范围

- 后端随机突击规则：允许窗口、勿扰、daily max、READY 库存阈值、疲劳惩罚、连续同缺陷后切换候选、缺陷画像配额和可重放决策时间源。
- 后端调度服务：生成 `SCHEDULED` session、到期发送 Web Push、通知失败/无订阅失败关闭、通知过期转 `EXPIRED`、接受后进入既有语音答辩闭环、延期一次、曝光后 abandon。
- Web Push：`push_subscription` 表、订阅 API、VAPID 配置校验、中性通知 payload、失效订阅停用。
- Web Push 安全边界：订阅 endpoint 拒绝非 HTTPS、userinfo、localhost、`.local`、非 443 端口、私网/回环/保留 IP；发送前 DNS 解析并阻断解析到内网地址；可信代理 fake-IP 场景需显式设置 `WEB_PUSH_ALLOW_FAKE_IP_HOSTS`，且只放行 198.18.0.0/15。
- 数据库：`0009_random_strike` 迁移，扩展 `training_session` 通知/接受/延期/推送字段，新增 `push_subscription`，新增用户级活跃 session 唯一部分索引。
- 前端 PWA：Service Worker push handler、订阅提交、首页等待/待接受/进行中/完成状态、接受前隐藏题目和来源、接受后恢复既有录音和答辩流程；已兼容浏览器授权后仍返回空 `PushSubscription` 的 MuMu Firefox 路径，改为受控显示“不支持通知”；`notificationclick` 已加固为同源 URL 解析、`client.navigate()` 失败后回退 `clients.openWindow()`，避免外部 URL 并提高通知点击落地可靠性；完成后刷新可用通知 URL 或本地保存的 session id 恢复完成页。
- 前端订阅失败降级：浏览器 `PushManager.subscribe()` 因 FCM/系统 push 服务不可用而 reject 时，`setupPushNotifications()` 返回 `unsupported`，避免把已知环境限制显示成泛化订阅失败。
- 登录态恢复：后端已有 refresh token 轮换能力；前端新增 `/auth/refresh` 调用，access token 仍使用 `sessionStorage`，refresh token 用 `localStorage` 保存，打开 PWA 时静默刷新，失败则清理本地 token 并回到登录页。
- 测试题可理解性：P10/P08 测试夹具和 Mock Provider 不再使用“请基于材料/材料显示”这类会让用户期待隐藏材料的文案，改为在题目文本中直接给出“已知事实”，完整来源仍按 SPEC/SOP 在完成后公开。
- 回归适配：旧的手动创建训练入口不再提前暴露题目，P03-P09 相关测试改为显式种子已曝光训练 session。

## 已修复的 review 问题

- 并发调度可能为同一用户创建多个活跃 session：已用唯一部分索引和 `IntegrityError` 兜底读回既有 session 修复。
- 用户控制的 Push endpoint 可能触发服务端内网访问：已增加 schema 校验、发送前校验和 DNS 解析后内网阻断。
- 领域评分内部调用 `datetime.now()` 导致决策不可重放：已改为由调度服务注入 `now`。
- 浏览器 push 服务注册失败时前端泛化报错：已把 `PushManager.subscribe()` reject 转为受控 `unsupported`，并用 `pushNotifications.test.ts` 覆盖。

## 已通过验证

后端：

```powershell
uv lock --check
uv run python scripts\verify_dependency_policy.py
uv run ruff check .
uv run ruff format --check .
uv run mypy app
$env:TEST_DATABASE_URL='postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking_test'; $env:TEST_DATABASE_SYNC_URL='postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test'; uv run pytest tests/test_push_endpoint_p10.py tests/test_random_strike_rules_p10.py tests/test_random_strike_p10.py tests/test_migrations_p10.py -q -rs
$env:TEST_DATABASE_URL='postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking_test'; $env:TEST_DATABASE_SYNC_URL='postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test'; uv run pytest -q -rs
```

结果：上述命令均通过；完整后端 pytest 仅跳过需要 `RUN_LIVE_SEARCH_TESTS=1` 与 `BOCHA_API_KEY` 的 P08 live Bocha smoke。存在既有 Starlette/httpx 与 Alembic `path_separator` deprecation warnings。

前端：

```powershell
pnpm --dir apps\web lint
pnpm --dir apps\web type-check
pnpm --dir apps\web test
pnpm --dir apps\web test -- src/pushNotifications.test.ts
pnpm --dir apps\web test -- pushHandler
pnpm --dir apps\web build
```

结果：上述命令均通过；本次通知点击、登录态、完成态恢复和 push 订阅失败降级加固后重新执行，Vitest 为 10 个文件、34 个测试通过；`pushHandler` 专项 3 个测试覆盖已有窗口导航、导航失败回退新窗口和拒绝 off-origin URL；`pushNotifications` 专项 3 个测试覆盖无订阅、`subscribe()` reject 降级和 subscribe 空返回后二次读取订阅；`trainingFlow` 新增测试覆盖通知 URL session id 优先、本地 session id 兜底，以及只恢复 `COMPLETED` 存储会话；`auth` API 测试覆盖 login 与 refresh；build 生成 `dist/sw.js` 与 `registerSW.js`。

仓库检查：

```powershell
git diff --check
```

结果：通过。

2026-06-25 最终 `$project-verify` 补充结果：

```powershell
uv lock --check
uv run python scripts/verify_dependency_policy.py
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q -rs
$env:TEST_DATABASE_URL='postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking_test'; $env:TEST_DATABASE_SYNC_URL='postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test'; uv run pytest tests/test_push_endpoint_p10.py tests/test_random_strike_rules_p10.py tests/test_random_strike_p10.py tests/test_migrations_p10.py -q -rs
$env:TEST_DATABASE_URL='postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking_test'; $env:TEST_DATABASE_SYNC_URL='postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking_test'; uv run pytest -q -rs
pnpm --dir apps\web lint
pnpm --dir apps\web type-check
pnpm --dir apps\web test
pnpm --dir apps\web build
git diff --check
```

结果：全部退出码 `0`。未带 DB env 的后端 pytest 会按门禁跳过 DB 集成/迁移；随后已用 `thinking_test` 补跑 P10 专项与全量后端 pytest。全量后端仅跳过 P08 live Bocha smoke，原因是未设置 `RUN_LIVE_SEARCH_TESTS=1` 和 `BOCHA_API_KEY`。

## MuMu 验收现状

当前探测命令：

```powershell
& 'D:\MuMu Player 12\shell\adb.exe' connect 127.0.0.1:16384
& 'D:\MuMu Player 12\shell\adb.exe' -s 127.0.0.1:16384 shell pm list packages | Select-String -Pattern 'gms|google|mozilla|firefox|chrom|browser|webview'
& 'D:\MuMu Player 12\shell\adb.exe' -s 127.0.0.1:16384 shell dumpsys package org.mozilla.firefox
& 'D:\MuMu Player 12\shell\adb.exe' -s 127.0.0.1:16384 shell dumpsys package com.android.chromium
& 'D:\MuMu Player 12\shell\adb.exe' -s 127.0.0.1:16384 shell dumpsys package org.ironfoxoss.ironfox
& 'D:\MuMu Player 12\shell\adb.exe' -s 127.0.0.1:16384 shell cmd package query-receivers -a org.unifiedpush.android.distributor.REGISTER
& 'D:\MuMu Player 12\shell\adb.exe' -s 127.0.0.1:16384 shell am start -n org.mozilla.firefox/org.mozilla.fenix.IntentReceiverActivity -a android.intent.action.VIEW -d http://127.0.0.1:5182/
& 'D:\MuMu Player 12\shell\adb.exe' -s 127.0.0.1:16384 shell am start -n com.android.chromium/org.chromium.chrome.browser.ChromeTabbedActivity -a android.intent.action.VIEW -d http://127.0.0.1:5182/
& 'D:\MuMu Player 12\shell\adb.exe' -s 127.0.0.1:16384 shell am start -n org.ironfoxoss.ironfox/org.mozilla.fenix.IntentReceiverActivity -a android.intent.action.VIEW -d http://127.0.0.1:5183/
```

证据：

- ADB 设备在线：`127.0.0.1:16384 device`
- 包列表命中：`package:com.android.webview`、`package:org.mozilla.firefox`、`package:com.android.chromium`、`package:io.heckel.ntfy`、`package:org.unifiedpush.distributor.sunup`、`package:org.ironfoxoss.ironfox`、`package:org.mozilla.fennec_fdroid`；未命中 `com.google.android.gms` 或 `com.android.vending`。
- Firefox/Fenix：安装包为 `org.mozilla.firefox`，`versionName=152.0`，安装后应用显示名为 Firefox 属正常表现，Fenix 的渠道/包名与启动器显示名不同；可打开 `http://127.0.0.1:5182/` 并登录测试账号；网页通知权限弹窗可出现并允许，但浏览器返回空订阅，ADB logcat 记录 `WebPushEngineDelegate: Error on push onSubscribe` 与 `AutoPushFeature ... PushApiException$InternalException: Internal Error: Communication Error: "No native id"`；`push_subscription` 计数保持 0。
- AOSP Chromium：安装包为 `com.android.chromium`，`versionName=110.0.5481.154.1`；显式启动 `ChromeTabbedActivity` 可打开本地 PWA 并登录；点击“开启通知”后页面显示 `Registration failed - push service error`；`push_subscription` 计数保持 0。
- Fennec F-Droid：安装包为 `org.mozilla.fennec_fdroid`，`versionName=152.0.0`，安装后显示名为 Fennec，包内存在 UnifiedPush connector receiver；但在 MuMu x86_64 中启动即崩溃，logcat 出现 `Process org.mozilla.fennec_fdroid ... has died`、`signal 11 (Segmentation fault)` 和 native bridge/houdini 相关日志，清除数据后仍无法进入 PWA。
- IronFox：安装包为 `org.ironfoxoss.ironfox`，`versionName=152.0`，x86_64 APK 来自 IronFox 官方 v152.0 release，安装后可打开页面，包内存在 `org.unifiedpush.android.connector` 相关 receiver。其站点设置默认 `网站设置 -> 通知 = 阻止`，切换为 `每次都问我` 后，`http://127.0.0.1:5183/` 诊断页显示 `isSecureContext=true`、`hasServiceWorker=true`、`hasPushManager=true`、`hasNotification=true`，权限可从 `default` 授权到 `granted`。但调用 `PushManager.subscribe()` 返回 `AbortError: Error retrieving push subscription.`，logcat 记录 `GeckoEventDispatcher: No listener for GeckoView:PushSubscribe`；安装并初始化 ntfy 与 Sunup 后重启 IronFox 复测仍相同，未出现 UnifiedPush `REGISTER` 或 `NEW_ENDPOINT`。
- Iceraven：安装包为 `io.github.forkmaintainers.iceraven`，`versionName=iceraven-2.45.0`，x86_64 APK 来自 GitHub latest release，SHA256 为 `CD5A61C172C669D977F44CAA56355978DCE4A27E2A2D04BD047AAC1D95A2F07E`。在 MuMu 中可打开诊断页并授权通知，但 `PushManager.subscribe()` 失败，logcat 同样记录 `No listener for GeckoView:PushSubscribe`，未形成网页 `PushSubscription`。
- UnifiedPush 环境反证：安装 F-Droid `ntfy` 与 `Sunup` 后，`cmd package query-receivers -a org.unifiedpush.android.distributor.REGISTER` 能发现两个 distributor；安装 F-Droid `UP-Example` 后可选择 Sunup 完成注册，拿到 `https://updates.push.services.mozilla.com/wpush/...` endpoint、`auth` 与 `p256dh`，点击 `Send notification` 后 logcat 显示 `ServerConnection: New message: Notification`、`UP_Distrib: Message forwarded`，`dumpsys notification` 中出现 `org.unifiedpush.example` 的 `UP-Example / WebPush test` 通知。该证据说明 MuMu + Sunup/UnifiedPush 能收 WebPush，P10 阻塞不是 distributor 或 MuMu 通知层本身不可用。
- API 日志只出现 `GET /api/v1/push/public-key`，未出现 `POST /api/v1/push/subscriptions`，说明失败发生在浏览器生成订阅阶段，不是后端保存失败。
- 此前 MuMu P10 本地验收中，无订阅负向路径已验证为 `EXPIRED`、`PUSH_STATUS=FAILED`、`PUSH_ERROR=NO_ACTIVE_PUSH_SUBSCRIPTION`，无 attempt/report/occurrence，题目保持未曝光。

结论：不是“MuMu 模拟器不能测试”，而是当前这套 MuMu 里没有 GMS，官方 Firefox/Fenix 与 Chromium 无法取得原生 push id；非 Google 路线中，ntfy/Sunup distributor 已被 UP-Example 证明可用，但 Fennec 在 MuMu 中崩溃，IronFox/Iceraven 的网页 `PushManager.subscribe()` 没有接到 GeckoView/UnifiedPush 监听器。因此当前 MuMu + 已测试浏览器组合仍无法证明 P10 的 PWA Web Push subscription 和系统通知到达。根据已批准计划，这一硬门槛不能用桌面浏览器、轮询或 UP-Example 代替。

## 物理手机 Chrome 验收现状

用户连接的物理设备：

```powershell
& 'D:\MuMu Player 12\shell\adb.exe' devices -l
& 'D:\MuMu Player 12\shell\adb.exe' -s 10AE2M0P60002R5 reverse --list
& 'D:\MuMu Player 12\shell\adb.exe' -s 10AE2M0P60002R5 shell dumpsys package com.android.chrome
& 'D:\MuMu Player 12\shell\adb.exe' -s 10AE2M0P60002R5 shell dumpsys package com.google.android.gms
```

证据：

- 设备在线：`10AE2M0P60002R5 device product:PD2324 model:V2324A device:PD2324`，Windows 识别为 vivo X100 Pro。
- 手机存在 `com.android.chrome`、`com.google.android.gms`、`com.android.vending` 和 `com.google.android.webview`；Chrome 为 `versionName=130.0.6723.102`，GMS 为 `versionName=26.23.34 (260400-933906539)`。
- 已建立 ADB reverse：`tcp:5182`、`tcp:8010`、`tcp:5183`；本地 `http://127.0.0.1:8010/api/v1/push/public-key`、`http://127.0.0.1:5182/`、`http://127.0.0.1:5183/` 均返回 200。
- 在手机 Chrome 打开 `http://127.0.0.1:5183/`，诊断页显示 `isSecureContext=true`、`hasServiceWorker=true`、`hasPushManager=true`、`hasNotification=true`，通知权限已为 `granted`；点击 `Subscribe` 后等待约 45 秒，页面返回 `subscribeError: "Registration failed - push service error"`、`name: "AbortError"`。
- 换用 `http://localhost:5183/` 复测，Chrome 弹出 `http://localhost:5183 想向您发送通知` 权限框，点击“允许”后权限变为 `granted`；再次点击 `Subscribe` 并等待约 55 秒，仍返回 `Registration failed - push service error`。
- 手机网络连通性探测：`mtalk.google.com:5228` 可连通；`fcmregistrations.googleapis.com:443`、`firebaseinstallations.googleapis.com:443`、`android.clients.google.com:443` 均超时。电脑本机同一时间可连通这些 443 端点，且本机存在 `verge-mihomo` 代理监听 `127.0.0.1:7897`。

结论：这台物理手机的 Chrome/GMS 环境满足浏览器能力和权限前置条件，但当前手机网络无法访问 FCM 注册 HTTPS API，因此 Chrome 不能生成网页 `PushSubscription`。如要继续完成 P10 正向实机验收，需要让手机网络可访问这些 Google/FCM 端点，或经用户确认后临时让手机通过电脑代理联网并在测试后恢复代理设置。

### 物理手机 Chrome 代理后追加结果

用户确认允许后，临时设置手机全局代理到电脑本机代理：

```powershell
& 'D:\MuMu Player 12\shell\adb.exe' -s 10AE2M0P60002R5 reverse tcp:7897 tcp:7897
& 'D:\MuMu Player 12\shell\adb.exe' -s 10AE2M0P60002R5 shell settings put global http_proxy 127.0.0.1:7897
```

证据：

- 设置前 `settings get global http_proxy` 为 `null`；设置后为 `127.0.0.1:7897`。本机 `verge-mihomo` 监听 `127.0.0.1:7897`，电脑经该代理访问 `fcmregistrations.googleapis.com`、`firebaseinstallations.googleapis.com`、`android.clients.google.com` 均能建立 HTTPS 连接。
- 强制重启手机 Chrome 后，`http://localhost:5183/` 诊断页 `PushManager.subscribe()` 成功，页面显示 `permission: "granted"`、`subscribed: true`、endpoint host 为 `fcm.googleapis.com`。
- 正式 PWA `http://localhost:5182/` 重新登录测试账号 `mumu-p10-firefox` 后，CDP 执行解除旧订阅、用新 VAPID 公钥重新订阅、提交 `/api/v1/push/subscriptions`；返回 `saveStatus=201`、`savedActive=true`、`newHost=fcm.googleapis.com`。
- 使用测试库 `thinking_mumu_p10_firefox_20260624_182332`。首次直接走当前 `PyWebPushSender` 时，发送前 DNS 防护把 FCM fake-IP 判为保留网段，结果为 `stage=EXPIRED`、`push_status=FAILED`、`push_error_code=WEB_PUSH_ENDPOINT_BLOCKED`。这说明本地代理/fake-IP 环境会误伤真实 FCM endpoint，不能把该路径记为正向通过。
- 随后用脚本内生成的 raw VAPID 测试 key 重启 8010 后端，公钥前缀 `BN2nWN1k`，不写入仓库、不打印私钥。受控 smoke 脚本临时跳过本机 fake-IP DNS 检查，并设置 `HTTPS_PROXY=http://127.0.0.1:7897` 后，`RandomStrikeService.send_due_notifications()` 返回 `sent_count=1`，session `beeb65a9-b952-46e5-a3e0-bc8fa5493ce0` 进入 `NOTIFIED`、`push_status=SUCCEEDED`、`push_error_code=None`。
- 手机 `dumpsys notification --noredact` 中出现 Chrome Web 通知，tag 为 `strike:beeb65a9-b952-46e5-a3e0-bc8fa5493ce0`，标题 `突击审核已到达`，正文 `预计用时约 3 分钟`，channel 为 `web:http://localhost:5182;...`。
- `GET /api/v1/trainings/current` 使用同一测试账号返回 `id=beeb65a9-b952-46e5-a3e0-bc8fa5493ce0`、`stage=NOTIFIED`、`notification_expires_at=2026-06-24T14:03:54.533783Z`。
- 手机 Chrome 打开通知 payload URL 并恢复登录态后，PWA 显示 `突击已到达`，`接受突击` enabled。点击 `接受突击` 后，UI 显示 `等待第一答`，`开始录音` enabled；数据库验证同一 session 为 `WAIT_FIRST_AUDIO`，`accepted_at` 和 `exposed_at` 已设置，绑定题目变为 `EXPOSED` 且 `exposed_count=1`。
- 该测试题的题干在数据库中本来就是 `?` 字符（`ord=63`），所以截图里的题干问号不是前端或 Chrome 编码问题；若后续要做视觉验收，应换成真实中文测试题夹具。
- P10 追修后新增 `WEB_PUSH_ALLOW_FAKE_IP_HOSTS=fcm.googleapis.com`，不再 monkeypatch `_validate_resolved_endpoint_addresses()`；直接调用真实 `PyWebPushSender` 返回 `delivered=True`、`error_code=None`，手机 `dumpsys notification` 出现 tag `p10-codefix:134725` 的 Chrome Web 通知。测试后确认手机 `http_proxy=null`。
- P10 追修后使用当前代码重新创建并发送 session `3a1f5178-8d99-4629-a156-60c398b3e659`：`RandomStrikeService.send_due_notifications()` 返回 `sent_count=1`，DB 为 `NOTIFIED/SUCCEEDED`，手机 Chrome 通知栈出现同 session tag。接受前 DB 为 `NOTIFIED`、题目 `READY/exposed_count=0`，手机 PWA 显示 `突击已到达` 且 `开始录音` disabled；接受后 DB 为 `WAIT_FIRST_AUDIO`、题目 `EXPOSED/exposed_count=1`，手机 PWA 显示真实中文题干与 `开始录音` enabled。
- 经用户允许，临时将手机 Chrome `RECORD_AUDIO` AppOp 放开，使用手机真实点击录制并上传三段音频：FIRST `06cb57a0-8364-4a32-ac6d-96f0c28e1699`（约 24.4s，391862 bytes）、FOLLOWUP `e8616b63-7f20-47b2-9a9b-8c29420632b2`（约 4.9s，77093 bytes）、FINAL `fd022410-f98f-4905-a4a8-49b361a62610`（约 4.9s，76957 bytes），三段均为 `UPLOADED`。
- 使用现有 worker 路径和 mock providers 单步处理三个 `GRAPH_RESUME` job 与一个 `EVALUATE_SESSION` job；三段 transcript 均为 `SUCCEEDED`，session 最终为 `COMPLETED`，评审报告 `status=COMPLETED`，分数为 logic `100`、speech `80`、adaptability `70`、final `90`，本次 mock 评审 issue 数为 0。
- 测试收尾：手机 `http_proxy=null`；已移除临时 DevTools forward；Chrome `RECORD_AUDIO` UID 级 AppOp 已恢复为 `ignore`。Android 仍显示包级 `RECORD_AUDIO: allow` 历史条目，不支持单 op reset，未执行整包 reset 以避免重置 Chrome 其他权限。
- 完成态恢复兜底已在同一台手机 Chrome 重跑确认：新建本地假账号 `p10-restore-phone-2240` 和 completed session `659951a4-6a28-4533-a0f1-b61794a8fd55`，API 前提为登录 200、`GET /api/v1/trainings/current` 返回 404、`GET /api/v1/trainings/{id}/state` 返回 `COMPLETED` 且带 `source_summary`、`GET /api/v1/trainings/{id}/provenance` 返回 200。手机 Chrome 打开 `http://localhost:5182/?session=659951a4-6a28-4533-a0f1-b61794a8fd55` 后登录，页面从 URL session 恢复并显示 `本轮答辩已完成`、`下一条` 和来源卡片。
- 登录态追修已完成：前端不再只依赖 `sessionStorage` access token；重新打开 PWA 时会使用本地 refresh token 调 `/api/v1/auth/refresh`，成功后轮换保存新 token 并恢复当前/完成训练状态，避免每次从手机 Chrome 打开都要求重新输入昵称密码。
- 题目文案追修已完成：测试夹具默认 prompt 从 `请基于材料说明...` 改为 `已知事实: 团队没有更新成功标准。请说明...`；Mock Provider 生成题也改为在题目中显式给出已知事实，避免“题目要求看材料但材料不可见”的抽象体验。
- 通知点击补测已通过到 PWA URL：早期只点标题/正文节点时，session `3a1f5178-8d99-4629-a156-60c398b3e659` 的真实 Push 通知和 tag `p10-click-debug-1782312911049` 的 PWA 生成通知都出现过“通知被消费但停留在 Launcher”；随后解析通知栏 XML，找到 `P10area` 的可点击祖先 `com.android.systemui:id/expandableNotificationRow`，bounds 为 `[56,557][1204,799]`，点击行内中上部 `(630,650)` 后，通知被消费且 `topResumedActivity` 变为 `com.android.chrome/com.google.android.apps.chrome.Main`。再次生成带唯一参数的 PWA Web 通知 `P10probe`，tag `p10-probe-probe1782313404182`，可点击行 bounds 为 `[56,1129][1204,1371]`，点击 `(630,1221)` 后 Chrome 被唤起，通知被消费；手机 UI 地址栏显示 `localhost:5182/?session=659951a4-6a28-4533-a0f1-b61794a8fd55&click_probe=probe1782313404182`，证明通知 `data.url` 能落到目标 PWA URL。

结论：物理手机 Chrome 已证明浏览器能力、FCM 订阅、系统通知到达、PWA 待接受态、接受后曝光、通知点击打开 PWA URL、首答/追问/最终答录音上传、转写和评审完成链路可行；本地 fake-IP DNS 与 SSRF 防护冲突已通过默认关闭配置修复；完成页恢复兜底也已在手机 Chrome 上补测通过。剩余验收风险是 MuMu 正向 Push 环境仍不可用。

## 后续复测参考

1. 如后续仍想补 MuMu 兼容性验证，可准备支持网页 Web Push 的 MuMu/Android 浏览器环境：优先是带可用 GMS/Google Play Services/FCM 的 MuMu 镜像，或一个已证明 `PushManager.subscribe()` 可生成真实 `PushSubscription` 的非 Google 浏览器组合；仅安装 Firefox/Fenix、AOSP Chromium、Fennec F-Droid、IronFox 152 或 Iceraven 2.45.0 在当前 MuMu 环境下仍不足。
2. 若继续使用物理手机 Chrome，先保证手机可访问 `fcmregistrations.googleapis.com:443`、`firebaseinstallations.googleapis.com:443` 和 `android.clients.google.com:443`；可由用户在手机上启用可访问 Google API 的网络/VPN，或经用户确认后临时设置手机全局代理到电脑 `verge-mihomo` 并在测试后恢复。
3. 如果开发机代理使用 fake-IP DNS，可在本地 smoke 环境显式设置 `WEB_PUSH_ALLOW_FAKE_IP_HOSTS=fcm.googleapis.com`；生产环境保持为空，除非运行环境同样有受控 fake-IP 代理。
4. 重新启动本地 API、scheduler 和 web dev server，使用测试库、mock AI/search/embedding 和临时非生产 VAPID keypair。
5. 通过 ADB reverse 暴露本地 API/web 到 MuMu 或物理手机。
6. 在目标 Android 环境中完成登录、通知权限、Push 订阅、scheduler 到期发送、系统通知到达、点击/打开 PWA、接受后才显示题目、录音上传、追问/最终答、评审完成。
7. 再跑负向验收：通知过期不评分、延期一次不曝光、通知失败或无订阅不评分、曝光后退出为 `ABANDONED` 且题目退役。
8. MuMu 复测通过后可补充记录为兼容性证据；按当前用户批准口径，它不是 P10 完成前置条件。

## 完成判断

P10 的代码和自动化测试当前通过，物理手机 Chrome/PWA App 已有真实发送、通知点击落地、完成页恢复兜底与完整录音/追问/评审链路证据。用户已明确接受先忽略 MuMu 模拟器验证，因此 P10 可按物理手机 App/PWA 验收口径标记完成；MuMu 网页 Push 正向环境不可用仅作为后续兼容风险记录。
