**产品与技术规格说明书（SPEC）**

| **文档版本** | v1.0                                   |
|--------------|----------------------------------------|
| **编制日期** | 2026-06-20                             |
| **适用对象** | 个人使用，最多 3-4 名独立用户          |
| **文档状态** | 初始开发基线 / 尚未开始开发              |

**核心定位：证据驱动、语音突击、缺陷自适应、题目永不重复**

# 文档使用说明

| **开发基线：**本文件是第一版可实施规格。除“待校准参数”外，P0规则视为冻结；涉及模型、搜索或语音供应商的内容通过 Provider 接口隔离，不得写死到业务层。 |
|------------------------------------------------------------------------------------------------------------------------------------------------------|

| **项**   | **说明**                                                                                                                                                  |
|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| 产品形态 | 移动端优先的可安装 PWA；核心闭环验证后，可用 Capacitor 封装原生应用。                                                                                     |
| 用户规模 | 1-4 人，互相数据隔离；无商业化、支付、组织管理和排行榜。                                                                                                  |
| 核心目标 | 通过随机语音突击、动态追问、严格评审和长期缺陷画像，提升实时思考、逻辑组织、口头表达、全局视角与团队管理能力。                                            |
| 技术基线 | Vue 3 + TypeScript + PWA；FastAPI；LangGraph StateGraph；PostgreSQL + pgvector；Python Worker；全部 AI 能力调用阿里云百炼线上模型，服务器不部署本地模型。 |
| 关键约束 | 用户不得选题型；题目必须有来源；历史题不可重复或换皮；第一次语音不可覆盖；所有负面评价必须有原话与时间点证据。                                            |

# 目录

- 1\. 产品背景与定位

- 2\. 核心产品原则

- 3\. 术语与能力模型

- 4\. 用户与权限

- 5\. 端到端业务流程

- 6\. 功能需求

- 7\. 个人缺陷画像与训练策略

- 8\. 来源驱动的题目生成

- 9\. 题目永不重复机制

- 10\. 语音突击训练流程

- 11\. 严格评审与评分

- 12\. 系统架构

- 13\. LangGraph 编排规格

- 14\. 数据模型

- 15\. API 规格

- 16\. AI Provider 与结构化输出

- 17\. 非功能需求

- 18\. 验收标准

- 19\. 风险与边界

- 20\. 技术参考资料

- 附录 A. 云端模型与环境变量规格

- 附录 B. Codex CLI 开发协作规格

# 1. 产品背景与定位

## 1.1 要解决的个人问题

- 面对上级、同事、下属或客户的问题时，容易从实现细节出发，忽略目标、决策、约束和利益相关方。

- 会后或思考后存在零散观点，但无法快速形成结论、依据、取舍与下一步行动。

- 临场被问时容易答非所问、过程代替结论、无证据下结论或陷入熟悉的技术细节。

- 文字整理可以掩盖真实问题，实际口头沟通中的反应力、压缩能力和追问应变仍然薄弱。

- 普通学习产品只给知识或模板，缺乏长期、跨场景、基于个人高频缺陷的持续复测。

## 1.2 产品定义

本系统是一个“证据驱动的 AI 语音思维审计与自适应训练系统”。系统在用户允许的时间边界内随机发起突击，以真实来源材料生成从未出现过的新问题；用户必须限时语音回答；AI通过动态追问、严格评审和历史缺陷匹配，持续更新个人能力与缺陷画像。

| **核心闭环：**个人缺陷画像 → 自动选择训练目标 → 检索真实来源 → 生成全新题目 → 随机语音突击 → 动态追问 → 严格评审 → 缺陷证据入库 → 后续跨场景复测。 |
|----------------------------------------------------------------------------------------------------------------------------------------------------|

## 1.3 产品目标

> **1.** 提高问题识别速度：先判断对方真正问什么，再进入方案和实现。
>
> **2.** 提高结论形成与口头表达能力：在有限时间内说清结论、依据、未知、取舍和行动。
>
> **3.** 提高全局与管理视角：能够考虑客户、团队、公司、成本、长期影响和组织机制。
>
> **4.** 提高认知校准能力：区分事实、假设和未知，并能在新信息出现后修正判断。
>
> **5.** 形成可追溯的个人经验库：明确哪些问题高频、严重、跨场景复发，以及是否真实改善。

## 1.4 P0 非目标

- 不做企业级会议纪要、项目管理、协同办公或知识库平台。

- 不做社交、排行榜、打卡社区、付费会员和公开题库。

- 不评价人格、智商、音色、口音、情绪稳定性或“是否适合当领导”。

- 不做模型训练、微调、强化学习、复杂多 Agent 自主决策。

- 不在服务器部署本地 LLM、ASR、TTS 或 Embedding 模型，不采购 GPU；P0 全部通过国内云端模型 API 调用。

- 不追求高并发；容量目标仅为 1-4 名用户。

## 1.5 版本范围

| **版本** | **范围**                                                                                                     | **明确不含**                                       |
|----------|--------------------------------------------------------------------------------------------------------------|----------------------------------------------------|
| P0 / MVP | PWA、账号、随机突击、语音录音、STT、LangGraph 多轮答辩、严格评审、缺陷经验库、来源证明、四级防重复、周报告。 | 原生商店发布、后台录音、实时全双工语音、团队排名。 |
| P1       | Capacitor 封装、推送可靠性增强、多模型路由、来源库存管理、题目质量人工审核台。                               | 大规模组织权限、商业化。                           |
| P2       | 更精细的自适应测量、个性化知识输入、多语言训练、长期效果评估。                                               | 开放社区与公开内容平台。                           |

# 2. 核心产品原则

| **编号**              | **原则**                                                                           |
|-----------------------|------------------------------------------------------------------------------------|
| P-01 语音优先         | 核心答题默认只接受语音；文字仅用于展示题目、转写纠错和查看报告。                   |
| P-02 用户不选题       | 用户只能设置可用时间和隐私边界；不能选择训练类型、缺陷、领域、难度和题型。         |
| P-03 有依据才出题     | 题目事实必须映射到可访问来源和证据片段；无合格来源时宁可少出题。                   |
| P-04 永不重复         | 历史原题、同义改写、数字换皮、结构换皮和答案骨架高度重复均禁止。                   |
| P-05 第一反应不可覆盖 | 第一次语音回答永久保留，不允许删除后重录；它是个人真实反应的主要证据。             |
| P-06 先追问再给答案   | AI不得在最终回答前直接公布完整参考答案，应先用追问暴露缺口。                       |
| P-07 评价必须有证据   | 每条负面评价必须引用原话、音频时间点、评分规则和置信度。                           |
| P-08 思维与表达分开   | 逻辑、口语和追问应变分别评分，避免语言流畅掩盖逻辑缺陷。                           |
| P-09 缺陷需重复确认   | 单次问题只能记为 occurrence；至少跨 2 个场景、出现 3 次后才可确认为稳定缺陷。      |
| P-10 失败关闭         | 来源、查重、Rubric 或证据复核任一失败，题目不得投放或报告不得定稿。                |
| P-11 规则确定性       | 分数封顶、查重阈值、来源门槛、最大追问次数由 Python 规则决定，不交给模型自由修改。 |
| P-12 可替换供应商     | LLM、STT、Embedding、Search 和 TTS 均通过 Provider 接口隔离。                      |

# 3. 术语与能力模型

## 3.1 核心术语

| **术语**             | **定义**                                                           |
|----------------------|--------------------------------------------------------------------|
| 能力维度 Ability     | 可训练、可观察的思维或沟通能力，例如问题识别、证据意识、系统视角。 |
| 缺陷 Defect          | 跨题目可复现的底层问题模式，例如“未明确目标就进入实现层”。         |
| 缺陷出现 Occurrence  | 某一次回答中，带原话和时间点证据的具体问题记录。                   |
| 缺陷画像 Profile     | 用户在各缺陷上的严重度、频率、置信度、复发和改善状态。             |
| 来源包 Source Bundle | 一组经过等级评估、抓取、冻结并可追溯的真实材料。                   |
| 事实原子 Claim       | 从来源中提取、可精确定位的事实或明确观点。                         |
| 题目指纹 Fingerprint | 领域、角色、冲突、约束、决策对象、推理骨架等结构特征。             |
| 冻结 Rubric          | 在用户答题前生成并保存的隐藏评分标准。                             |
| 近迁移 / 远迁移      | 在相近场景 / 完全不同场景中复测同一个底层缺陷。                    |
| 训练线程 Thread      | 一次突击训练对应一个 LangGraph thread_id，贯穿暂停与恢复。         |

## 3.2 能力树

| **能力域**     | **要观察的行为**                                                       |
|----------------|------------------------------------------------------------------------|
| 问题识别       | 是否回答真正的问题；是否区分目标、决策、方案和实现；是否识别核心矛盾。 |
| 结构化思维     | 是否结论先行；理由是否支持结论；信息是否同层、可压缩。                 |
| 信息与证据     | 是否区分事实、假设、未知；是否知道还缺什么；是否避免无依据断言。       |
| 因果与推演     | 因果链是否完整；是否考虑替代原因、反例和二阶影响。                     |
| 决策与取舍     | 是否有备选方案、比较标准、资源约束和明确放弃项。                       |
| 系统与全局     | 是否看到客户、团队、公司、长期、成本、机会成本与组织激励。             |
| 团队管理       | 是否区分能力、意愿、机制、权责和资源问题；是否会授权和纠偏。           |
| 沟通与视角转换 | 是否理解对方关注层级；能否针对领导、同事、下属、客户调整表达。         |
| 行动闭环       | 是否有可见产物、负责人、时间、验证方式和失败后的调整。                 |
| 口语表达       | 结论速度、结构可听性、简洁度、停顿质量、口头禅和时间控制。             |
| 追问应变       | 是否听懂追问、承认未知、根据新信息更新观点并保持前后一致。             |

# 4. 用户与权限

| **角色** | **权限**                                                                             |
|----------|--------------------------------------------------------------------------------------|
| USER     | 接受突击、提交语音、查看自己的报告和来源、纠正转写、发起申诉、删除或导出自己的数据。 |
| ADMIN    | 创建邀请码、禁用账号、查看系统健康和任务失败；默认不得查看其他用户的语音与详细回答。 |

| **数据隔离：**所有业务查询必须以 user_id 为强制过滤条件。管理员若需排障，只能查看任务状态、错误码和脱敏日志；读取原始语音必须由用户显式授权。 |
|-----------------------------------------------------------------------------------------------------------------------------------------------|

# 5. 端到端业务流程

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>用户完成首次设置<br />
↓<br />
系统建立 7 天基线画像<br />
↓<br />
后台根据缺陷优先级准备“有来源且未重复”的题目库存<br />
↓<br />
在允许时间窗口内随机发起 Web Push<br />
↓<br />
用户接受突击，听取问题，限时语音回答<br />
↓<br />
LangGraph 暂停/恢复：第一答 → 追问 → 最终答<br />
↓<br />
并行完成逻辑、口语、应变评审与证据复核<br />
↓<br />
记录缺陷 occurrence，更新 profile<br />
↓<br />
展示报告、来源和历史相似问题<br />
↓<br />
系统下一次使用全新来源和场景复测同一底层能力</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 5.1 首次使用

> **1.** 管理员创建邀请码，用户以昵称、密码注册。
>
> **2.** 用户设置可接受突击时间窗口、每日最大次数、勿扰时段、原始音频保留策略。
>
> **3.** 用户授予麦克风与通知权限；系统完成录音、播放和通知自检。
>
> **4.** 前 7 天进入基线模式：覆盖多个能力域，不提前公布检测方向。
>
> **5.** 基线结束后，只将有充分证据的问题确认为缺陷；其余标记为“待观察”。

## 5.2 日常突击

| **阶段** | **默认规则**                                                    |
|----------|-----------------------------------------------------------------|
| 通知     | 只显示“突击审核已到达”和预计用时，不显示领域、能力或缺陷。      |
| 接受     | 通知有效期默认 5 分钟；未接受不计能力分。                       |
| 问题播放 | 题目默认播放一次，P0 可允许重听一次；显示文字由系统按难度决定。 |
| 准备     | 默认 10 秒，仅允许记录最多 3 个关键词。                         |
| 第一回答 | 默认 90 秒，一镜到底，不显示实时转写，不允许覆盖。              |
| 追问     | 1-2 轮，每轮 30-60 秒；追问针对最大逻辑缺口。                   |
| 最终回答 | 默认 45-60 秒，要求前 10 秒给出结论。                           |
| 评审     | 逻辑、口语、应变分开；每条问题提供音频定位。                    |
| 来源公开 | 完成最终回答后公开全部来源、证据映射和题目加工说明。            |

# 6. 功能需求

| **编号** | **模块**       | **P0要求**                                                                     |
|----------|----------------|--------------------------------------------------------------------------------|
| FR-01    | 账号与首次设置 | 邀请码注册、登录、训练窗口、勿扰、每日次数、音频保留、通知/麦克风自检。        |
| FR-02    | 自适应训练策略 | 系统依据缺陷画像决定目标、场景、题型、难度和迁移方式；用户不可选择。           |
| FR-03    | 随机突击调度   | 在允许窗口随机安排；避免固定时间；已曝光未完成题永久退役。                     |
| FR-04    | 来源检索与核验 | 抓取网页/PDF，评估来源等级，提取事实原子，保存位置和快照哈希。                 |
| FR-05    | 问题生成       | 基于已核验事实生成候选题；题目事实支持率必须 100%。                            |
| FR-06    | 题目防重复     | 原文、语义、结构、答案骨架四级查重；同事件默认不复用。                         |
| FR-07    | 语音答辩       | 题目播放、倒计时、录音、上传、追问、最终答、断点和异常处理。                   |
| FR-08    | LangGraph 编排 | 使用 StateGraph、interrupt、持久化 checkpoint 实现暂停、恢复、重试和条件分支。 |
| FR-09    | 语音转写与指标 | 保存原音频、逐字稿、校正版、词级时间戳、停顿和口头禅指标。                     |
| FR-10    | 严格逻辑评审   | 冻结 Rubric、回答结构提取、问题识别、Python 封顶、独立证据复核。               |
| FR-11    | 动态追问       | 根据最大缺口产生目标、证据、反例、取舍、利益相关方或管理追问。                 |
| FR-12    | 缺陷经验库     | 记录问题编码、原话、时间点、严重度、置信度、跨场景和纠正后复发。               |
| FR-13    | 个人画像       | 维护待观察、已确认、高优先、改善中、稳定改善等状态及训练优先级。               |
| FR-14    | 报告与趋势     | 本次报告、前后回答对比、历史相似问题、周度问题与改善报告。                     |
| FR-15    | 纠错与申诉     | 转写纠错、重复题投诉、来源错误、评审误解和分类错误申诉。                       |
| FR-16    | 隐私与删除     | 用户可删除单条训练、原始音频、账号及全部数据；支持导出个人数据。               |
| FR-17    | 最小后台       | 邀请码、用户状态、任务失败、题目库存、来源失效、系统健康。                     |

## 6.1 P0 页面清单

| **页面**        | **主要内容**                                                               |
|-----------------|----------------------------------------------------------------------------|
| 登录 / 邀请注册 | 昵称、密码、邀请码；不接短信和第三方登录。                                 |
| 首次设置        | 时间窗口、每日次数、勿扰、数据保留、权限自检。                             |
| 首页            | 仅显示是否有待处理突击、最近一次重点问题和本周趋势；不提前显示下一题类型。 |
| 突击训练        | 题目播放、准备倒计时、录音、追问、最终答、处理进度。                       |
| 本次报告        | 三类评分、时间轴问题、历史相似问题、来源、申诉入口。                       |
| 缺陷经验库      | 高频严重、最近复发、跨场景、改善中、已稳定改善。                           |
| 周报告          | 首次回答质量、复发率、迁移率、修正能力、口语趋势。                         |
| 设置            | 训练时间、通知、麦克风、原始音频保留和账号删除。                           |
| 最小后台        | 邀请码、失败任务、题目库存和来源异常。                                     |

# 7. 个人缺陷画像与训练策略

## 7.1 缺陷分类基线

| **编码**  | **名称**             | **判定含义**                                 |
|-----------|----------------------|----------------------------------------------|
| ALIGN-01  | 答非所问             | 未回应题目或对方真正要求的决策。             |
| LEVEL-01  | 过早进入实现层       | 目标或决策未明确就讨论代码、流程或任务拆分。 |
| LEVEL-02  | 局部问题替代整体问题 | 用自己熟悉的小问题替代系统问题。             |
| GOAL-01   | 把手段当目标         | 方案、工具或动作被当作最终价值。             |
| GOAL-02   | 缺少成功标准         | 无法说明做到什么程度才算有效。               |
| STRUCT-01 | 没有明确结论         | 大量描述后仍无法识别主张。                   |
| STRUCT-02 | 过程代替结论         | 只汇报做过什么，不说明当前判断和结果。       |
| STRUCT-03 | 层级混乱             | 目标、理由、风险和行动交叉堆叠。             |
| STRUCT-04 | 框架正确但内容空泛   | 只说通用模板，未结合本题事实。               |
| INFO-01   | 事实与假设混淆       | 把推测当作已确认事实。                       |
| INFO-02   | 信息不足仍强行下结论 | 不说明未知、边界和暂定性。                   |
| EVID-01   | 证据不支持结论       | 依据与结论之间缺少支撑。                     |
| CAUSE-01  | 因果链断裂           | 从现象直接跳到结论。                         |
| CAUSE-02  | 单因解释复杂问题     | 忽略替代原因和相互作用。                     |
| DEC-01    | 没有备选方案         | 决策题只给一个方案。                         |
| DEC-02    | 没有取舍标准         | 没有说明为什么选、放弃什么。                 |
| RISK-01   | 缺少反例与失败预案   | 未考虑什么会推翻判断。                       |
| SYS-01    | 忽略利益相关方       | 遗漏客户、团队、公司或合作方。               |
| SYS-02    | 局部最优代替整体最优 | 只优化自己或本部门。                         |
| SYS-03    | 忽略长期或二阶影响   | 只看直接、短期结果。                         |
| MGMT-01   | 把人的问题当流程问题 | 未判断能力、意愿、冲突和权责。               |
| MGMT-02   | 责任与决策权不清     | 没有明确谁负责、谁拍板。                     |
| MGMT-03   | 只安排任务不处理动机 | 忽略激励、认同和行为边界。                   |
| MGMT-04   | 过度依赖个人执行     | 倾向自己完成，而非通过团队交付。             |
| COMM-01   | 重点不清             | 信息多但听众无法识别主线。                   |
| COMM-02   | 对象不匹配           | 没有根据领导、同事、下属或客户调整表达。     |
| EXEC-01   | 行动抽象             | “研究、看看、梳理”没有可见产物。             |
| EXEC-02   | 缺少责任或期限       | 无法形成执行闭环。                           |
| EXEC-03   | 缺少验证标准         | 没有说明如何判断行动是否有效。               |
| SPEECH-01 | 结论出现过晚         | 前段铺垫过长。                               |
| SPEECH-02 | 重复与口头禅过多     | 影响可听性和信息密度。                       |
| SPEECH-03 | 长句混合多个层级     | 一句话承载结论、背景、风险和行动。           |
| ADAPT-01  | 未回应追问核心       | 被追问后继续重复原答案。                     |
| ADAPT-02  | 新信息下拒绝更新     | 证据变化仍机械固守。                         |

## 7.2 缺陷状态

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>OBSERVED（单次出现）<br />
↓ 满足至少 3 次、跨 2 个场景、2 次无提示<br />
CONFIRMED（已确认）<br />
↓ 严重度高或纠正后复发<br />
HIGH_PRIORITY（高优先）<br />
↓ 多次跨场景通过<br />
IMPROVING（改善中）<br />
↓ 连续 5 次跨场景未复发，且至少 2 次压力追问通过<br />
STABLE_IMPROVED（稳定改善）<br />
↘ 以后低频抽检；复发则回退</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 7.3 训练优先级

P0 使用规则分数，不使用复杂 IRT。所有输入先归一化到 0-1，初始公式如下：

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>priority = 100 × (<br />
0.28 × severity<br />
+ 0.20 × recent_frequency<br />
+ 0.18 × recurrence_after_feedback<br />
+ 0.14 × cross_domain<br />
+ 0.10 × days_since_test<br />
+ 0.10 × information_uncertainty<br />
- 0.15 × recent_training_fatigue<br />
)</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

- 每周题目分配建议：55% 高频严重缺陷，25% 跨场景迁移，10% 潜在缺陷，10% 能力盲区。

- 连续 2 次针对同一缺陷后，至少插入 1 次其他能力审核，防止猜题和疲劳。

- 系统保存每次自动选题原因，但在用户答题前不可见。

# 8. 来源驱动的题目生成

## 8.1 来源等级

| **等级** | **来源类型**                                                                      | **使用规则**                             |
|----------|-----------------------------------------------------------------------------------|------------------------------------------|
| S        | 政府/监管正式文件、裁判文书、官方调查、上市公司披露、原始统计、用户本人真实材料。 | 可作为关键事实直接依据。                 |
| A        | 同行评审论文、大学/研究机构案例、专业组织报告、企业官方技术复盘。                 | 可直接使用，但须核验发布日期和上下文。   |
| B        | 可靠媒体深度报道、署名专业分析。                                                  | 关键事实至少需要另一个独立来源印证。     |
| C        | 自媒体、论坛、社交媒体、无作者或无数据来源文章。                                  | 只能作为待分析观点，不得作为已确认事实。 |

## 8.2 生成流水线

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>选择目标缺陷与迁移方式<br />
↓<br />
生成检索方向（不是直接生成题目）<br />
↓<br />
搜索并抓取来源 → 来源评级 → 去重与时效检查<br />
↓<br />
提取事实原子 Claim，并保存证据位置<br />
↓<br />
独立模型复核 Claim 是否被来源支持<br />
↓<br />
基于 Claim 生成 8-12 道候选题<br />
↓<br />
逐句事实映射：unsupported_claim_count 必须为 0<br />
↓<br />
四级防重复 + 独立终审<br />
↓<br />
生成并冻结隐藏 Rubric<br />
↓<br />
保存来源包、题目、指纹、Rubric、提示词版本<br />
↓<br />
进入待投放库存</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 8.3 事实原子要求

| **字段**         | **要求**                                     |
|------------------|----------------------------------------------|
| claim_text       | 简洁陈述一个事实或明确观点，不混合多个命题。 |
| source_id        | 唯一指向原始来源。                           |
| evidence_locator | 网页段落、章节、小标题或 PDF 页码/段落。     |
| evidence_excerpt | 仅保存支持该事实所需的短片段。               |
| support_status   | VERIFIED / CONFLICTED / UNSUPPORTED。        |
| valid_until      | 对时效性事实设重新核验日期。                 |
| snapshot_hash    | 保存抓取内容或文件的哈希，保证可追溯。       |

| **发布门槛：**unsupported_claim_count = 0；来源有效；来源冲突已披露；题目、来源、Rubric 在用户答题前完成冻结。 |
|----------------------------------------------------------------------------------------------------------------|

## 8.4 题目事实与假设

- 默认禁止模型补充来源中不存在的人数、金额、时间、情绪、因果或角色关系。

- 反事实训练可加入受控假设，但必须记录 hypothetical_assumption，并在答题后明确披露。

- 来源中的实际决策不是唯一标准答案；评审关注用户的逻辑质量和取舍依据。

- 同一 source_event_id 默认只使用一次；案例深挖必须由管理员显式开启，日常突击不得复用。

# 9. 题目永不重复机制

## 9.1 重复定义

| **类型** | **示例或规则**                                         |
|----------|--------------------------------------------------------|
| 原题重复 | 文本相同或仅有标点、顺序差异。                         |
| 同义改写 | 意义、决策和答案骨架相同，只换表达。                   |
| 参数换皮 | 仅替换数字、人名、行业、功能名。                       |
| 角色换皮 | 角色名称不同，但关系、冲突、约束与目标相同。           |
| 结构重复 | 场景不同，但核心决策对象、推理路径和评分蓝图高度一致。 |
| 答案重复 | 用户仅记住上一题答案即可完成新题。                     |

## 9.2 四级查重

| **级别**      | **实现**                                                       | **初始判定**                                           |
|---------------|----------------------------------------------------------------|--------------------------------------------------------|
| L1 规范化哈希 | 去标点、数字、人名、公司名、同义角色后计算哈希。               | 命中即拒绝。                                           |
| L2 Embedding  | 题目文本、摘要、决策对象分别向量化，与全部历史题精确余弦检索。 | \>=0.92 拒绝；0.82-0.92 进入终审；阈值需用回归集校准。 |
| L3 结构指纹   | 比较领域、角色、冲突、约束、时间跨度、题型、推理骨架、Rubric。 | 同缺陷复测至少改变 4 个维度；高频缺陷至少改变 6 个。   |
| L4 LLM 终审   | 将最相似的 5-10 道历史题与候选题一并评估。                     | 若旧答案可直接套用、属换皮或答案骨架过度重合，则拒绝。 |

| **用户最终裁决：**用户可标记“明显换皮”。该题立即作废、不计分，题目和模板家族进入永久禁用，并重新生成全新题目。 |
|----------------------------------------------------------------------------------------------------------------|

## 9.3 题目指纹

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>{<br />
"domain": "客户合同",<br />
"user_role": "部门负责人",<br />
"stakeholders": ["客户", "研发", "销售", "财务"],<br />
"conflict_type": "短期收入与长期交付风险",<br />
"decision_object": "是否接受定制条件",<br />
"time_horizon": "一年合同周期",<br />
"resource_constraints": ["人员不可增加", "发布日期固定"],<br />
"task_form": "60秒向总经理汇报",<br />
"target_defects": ["LEVEL-01", "SYS-01"],<br />
"expected_reasoning": ["目标", "证据", "利益相关方", "方案比较", "取舍", "行动"],<br />
"template_family": "CUSTOMER_CONTRACT_SCOPE"<br />
}</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

# 10. 语音突击训练流程

## 10.1 会话状态机

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>SCHEDULED → NOTIFIED → ACCEPTED → QUESTION_EXPOSED<br />
→ WAIT_FIRST_AUDIO → PROCESS_FIRST<br />
→ WAIT_FOLLOWUP_AUDIO ↔︎ PROCESS_FOLLOWUP（最多 2 轮）<br />
→ WAIT_FINAL_AUDIO → EVALUATING → COMPLETED<br />
<br />
异常分支：EXPIRED / ABANDONED / INVALID / FAILED_RETRYABLE</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

| **状态**         | **关键规则**                                             |
|------------------|----------------------------------------------------------|
| SCHEDULED        | 已分配题目和随机时间，用户不可见题型。                   |
| NOTIFIED         | 推送已发；未接受不计能力分。                             |
| QUESTION_EXPOSED | 题目已播放或文字已显示；后续退出则题目永久退役。         |
| WAIT\_\*\_AUDIO  | LangGraph interrupt 暂停，等待外部上传 attempt_id。      |
| PROCESS\_\*      | STT、结构提取、追问生成或评审任务执行。                  |
| COMPLETED        | 报告、来源、缺陷记录均已完成。                           |
| INVALID          | 来源错误、转写无法使用、题目重复或评审证据不足；不计分。 |

## 10.2 录音规范

- 单次音频目标 30-120 秒，最大 180 秒；P0 录音时应用保持前台。

- 不显示实时转写，不提供删除后重录；允许用户提前结束。

- 录音成功后先落本地临时文件，再上传；上传成功后由服务端确认是否删除本地缓存。

- 保存原始音频、原始逐字稿、含义校正版。校正版只能修正 STT 识别错误，不能重写表达。

- 转写保留词级时间戳或至少片段级时间戳，以支持点击评审问题跳转音频。

- 原始音频默认保留 30 天，可由用户选择 7/30/90 天或长期保留。

## 10.3 反应力指标

| **指标**         | **说明**                                      |
|------------------|-----------------------------------------------|
| 首次开口时间     | 问题播放结束到首次有效发声；不鼓励 0 秒抢答。 |
| 首次有效结论时间 | 首次出现可识别判断的时间。                    |
| 问题识别速度     | 多久能说明真正要解决的目标或矛盾。            |
| 结构建立速度     | 是否快速形成主线，而非连续跳跃。              |
| 追问响应速度     | 是否抓住追问核心，而非重复原答案。            |
| 修正速度         | 新信息出现后，多久调整结论及依据。            |
| 表达恢复能力     | 被追问或打断后能否回到主线。                  |

# 11. 严格评审与评分

## 11.1 评审流水线

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>冻结 Rubric（答题前）<br />
↓<br />
STT + 时间戳 + 语音统计<br />
↓<br />
回答结构提取：结论、事实、假设、未知、角色、方案、取舍、风险、行动<br />
↓<br />
逻辑初评 + 口语分析 + 应变评审（可并行）<br />
↓<br />
独立证据复核：每条问题必须能定位原话<br />
↓<br />
Python 规则计算权重和封顶<br />
↓<br />
历史缺陷匹配与根因判断<br />
↓<br />
生成报告；用户可纠错与申诉</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 11.2 逻辑评分维度

每题根据隐藏 Rubric 选择适用维度并重新归一化到 100 分。默认权重仅作为起点：

| **维度**         | **默认权重** | **审查内容**                                       |
|------------------|--------------|----------------------------------------------------|
| 对题与问题定义   | 20           | 是否回答核心问题，是否识别目标、决策和主要矛盾。   |
| 结论与结构       | 15           | 是否结论明确、层级清晰、理由与结论对应。           |
| 事实、假设与证据 | 15           | 是否区分已知未知，证据是否支持判断。               |
| 因果与反例       | 10           | 因果链、替代解释、可推翻条件。                     |
| 系统与利益相关方 | 10           | 是否考虑组织、客户、团队、长期和二阶影响。         |
| 方案与取舍       | 15           | 是否有备选方案、比较标准、代价与放弃项。           |
| 风险与行动闭环   | 10           | 风险、验证、负责人、时间和调整机制。               |
| 管理与对象适配   | 5            | 管理题是否处理权责、激励、协作；表达是否匹配对象。 |

## 11.3 口语评分维度

| **维度**                   | **来源**                  |
|----------------------------|---------------------------|
| 结论出现速度、开场直接度   | 时间戳 + 语义定位。       |
| 结构可听性、压缩能力       | LLM 语义评审 + 句段结构。 |
| 语速、停顿、超时           | 程序统计。                |
| 口头禅、重复片段、未完成句 | 规则统计 + 语义去重。     |
| 长句与层级堆叠             | 句段时长 + LLM 判断。     |
| 对象适配与术语控制         | 结合题目设定的沟通对象。  |

## 11.4 追问应变评分

- 是否准确识别 AI 追问的核心，而非机械重复第一答。

- 是否承认未知并提出需要补充的信息。

- 新事实出现后是否合理调整，且说明为什么调整。

- 是否保持关键原则一致，避免无理由前后矛盾。

- 最终回答能否吸收追问并压缩成更清晰的结论。

## 11.5 硬性封顶规则

| **问题**                       | **总分上限** |
|--------------------------------|--------------|
| ALIGN-01：未回答题目核心       | 40           |
| 需要做决策但无明确结论         | 55           |
| 把未经证明的假设当事实         | 50           |
| 题目要求权衡但只有一个方案     | 60           |
| 战略/管理题完全以实现细节回答  | 50           |
| 只有通用框架、没有本题具体内容 | 60           |
| 来源或题目本身被判无效         | 不计分       |

## 11.6 评审问题输出要求

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>{<br />
"code": "LEVEL-01",<br />
"name": "过早进入实现层",<br />
"severity": 5,<br />
"confidence": "high",<br />
"evidence": [{"quote": "后面数据库可以先拆成三张表……", "start": 42.1, "end": 57.4}],<br />
"why_it_matters": "题目要求做范围决策，但回答尚未说明目标和取舍。",<br />
"missing_information": ["业务目标", "范围取舍", "验证标准"],<br />
"historical_match": {"defect_code": "LEVEL-01", "occurrence_count": 7},<br />
"correction_rule": "先说明目标与决策，再补充实现风险。"<br />
}</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

| **公平性要求：**系统只能评价“本次回答中未体现什么”，不能把未表达直接等同于人格缺陷；对人格、智商、口音、音色和情绪做推断一律禁止。 |
|------------------------------------------------------------------------------------------------------------------------------------|

# 12. 系统架构

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>┌──────────────────────── Vue3 PWA ────────────────────────┐<br />
│ 登录 / 推送 / 题目播放 / 倒计时 / 录音 / 上传 / 报告 │<br />
└──────────────────────────┬──────────────────────────────┘<br />
│ HTTPS / REST / Polling(P0)<br />
▼<br />
┌──────────────────────── FastAPI ─────────────────────────┐<br />
│ 鉴权 │ 用户设置 │ 训练会话 │ 音频上传 │ 报告 │ Web Push │<br />
└──────────┬───────────────────┬───────────────────────────┘<br />
│ │<br />
▼ ▼<br />
PostgreSQL + pgvector Python Worker / Scheduler<br />
业务数据 + checkpoint LangGraph / 云端 STT / 云端 LLM / Search<br />
│ │<br />
└──────────┬────────┘<br />
▼<br />
本地音频目录（P0）</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 12.1 技术栈

| **层**    | **选型**                                                                           | **说明**                                                                 |
|-----------|------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| 前端      | Vue 3、TypeScript、Vite、Pinia、Vue Router、vite-plugin-pwa                        | 移动端优先，PWA 安装到桌面。                                             |
| API       | Python 3.12、FastAPI、Pydantic v2                                                  | REST、鉴权、上传、自动 OpenAPI。                                         |
| ORM/迁移  | SQLAlchemy 2、Alembic、asyncpg                                                     | 异步数据库访问和版本化迁移。                                             |
| 编排      | LangGraph StateGraph                                                               | 长流程、interrupt、checkpoint、条件分支、并行节点。                      |
| 数据库    | PostgreSQL 16 + pgvector                                                           | 业务数据、任务表、向量检索。                                             |
| 语音      | MediaRecorder；阿里云 fun-asr 云端 STT Provider                                    | 保留词级或片段级时间戳；录音上传后由云端识别，应用服务器不加载语音模型。 |
| 模型      | 阿里云千问 OpenAI-compatible Provider；qwen3.5-plus / qwen3.6-plus，使用结构化输出 | API Key、Base URL 和模型 ID 全部由服务端环境变量配置。                   |
| 搜索/抓取 | Search Provider + httpx + trafilatura + PyMuPDF                                    | 检索来源并提取证据。                                                     |
| 调度      | APScheduler + DB 持久化任务                                                        | 随机突击、题目库存补充、周报告。                                         |
| 部署      | Docker Compose + Nginx + HTTPS                                                     | 单机满足 1-4 用户。                                                      |

## 12.2 进程职责

| **进程**  | **职责**                                                 |
|-----------|----------------------------------------------------------|
| web       | 静态 PWA 页面和 Service Worker。                         |
| api       | HTTP 接口、鉴权、上传、训练状态查询、push subscription。 |
| worker    | 执行 LangGraph、STT、LLM、抓取、查重和评审。             |
| scheduler | 随机调度、库存补充、音频清理、周报告。                   |
| postgres  | 业务表、pgvector、AI job、LangGraph checkpointer 表。    |
| nginx     | TLS、反向代理、上传限制、静态缓存。                      |

# 13. LangGraph 编排规格

## 13.1 图划分

| **图**                     | **用途**                                                                | **是否含 interrupt** |
|----------------------------|-------------------------------------------------------------------------|----------------------|
| question_preparation_graph | 选择缺陷、检索来源、提取 Claim、生成候选题、查重、冻结 Rubric、入库存。 | 否                   |
| voice_training_graph       | 第一回答、追问、最终回答、并行评审、证据复核、报告生成。                | 是，至少 3 次        |
| profile_update_graph       | 聚合 occurrence、更新缺陷状态与优先级、生成下一阶段策略。               | 否                   |

## 13.2 voice_training_graph 节点

| **节点**                 | **输入/输出**                            | **失败策略**                       |
|--------------------------|------------------------------------------|------------------------------------|
| load_frozen_question     | question_id → 来源、Rubric、题目播放文本 | 题目状态非 READY 则终止。          |
| wait_first_audio         | interrupt → attempt_id                   | 等待无限期；业务层负责过期。       |
| transcribe_first         | 音频 → 转写和时间戳                      | 自动重试 2 次；仍失败则 INVALID。  |
| extract_answer_structure | 转写 → 结构化回答                        | 结构化输出校验失败重试。           |
| select_followup          | 最大缺口 → 追问类型和内容                | 最多 2 轮。                        |
| wait_followup_audio      | interrupt → attempt_id                   | 同一 round 唯一键，保证幂等。      |
| evaluate_revision        | 比较前后回答，决定继续追问或进入最终答   | 条件路由。                         |
| wait_final_audio         | interrupt → final attempt_id             | 题目已曝光，退出则 ABANDONED。     |
| parallel_evaluation      | 逻辑、口语、应变、历史召回并行           | 单分支失败可重试，全部完成后汇合。 |
| verify_evidence          | 检查每条评价的原话证据和时间点           | 不通过则退回初评修订。             |
| apply_score_rules        | Python 计算权重和封顶                    | 确定性节点，不调用模型。           |
| persist_occurrences      | 写入问题记录和 evidence                  | 幂等 upsert。                      |
| finalize_report          | 生成用户报告并完成会话                   | 报告写入后状态 COMPLETED。         |

## 13.3 State 约束

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>class TrainingState(TypedDict, total=False):<br />
session_id: str<br />
user_id: str<br />
question_id: str<br />
current_stage: str<br />
followup_round: int<br />
max_followup_rounds: int<br />
first_attempt_id: str<br />
followup_attempt_ids: list[str]<br />
final_attempt_id: str<br />
answer_structure: dict<br />
draft_review: dict<br />
verified_review: dict<br />
speech_metrics: dict<br />
matched_defect_ids: list[str]<br />
awaiting_input_type: str<br />
error_code: str | None</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

- State 只保存流程所需的小对象和业务 ID；不得保存音频二进制、完整网页、PDF、全部历史记录或 embedding。

- 一次训练使用一个稳定 thread_id，建议直接使用 training_session.id。

- 生产使用持久化 Postgres checkpointer；短期线程状态与长期缺陷画像分离。

- interrupt 所在节点恢复时会从节点开头重新执行，因此 interrupt 前的副作用必须幂等，或拆为独立节点。

- 所有数据库写入使用业务唯一键，例如 (session_id, stage, round)，避免恢复时重复创建。

## 13.4 执行与重试

| **类型**       | **规则**                                                               |
|----------------|------------------------------------------------------------------------|
| 外部 API       | 指数退避，最多 3 次；记录 provider、model、request_id、耗时和 token。  |
| STT            | 可重试 2 次；必要时切换备用 Provider。                                 |
| 结构化输出校验 | 先用同模型修复 1 次，再切备用模型；仍失败则任务 FAILED_RETRYABLE。     |
| 数据库写入     | 事务 + 幂等键；可安全重放。                                            |
| 来源抓取       | 超时、403、动态页面失败时更换来源；不得用无正文 snippet 代替证据。     |
| 会话超时       | 用户未接受、未上传、浏览器关闭分别由业务状态机处理，不等同于能力失败。 |

# 14. 数据模型

## 14.1 核心表

| **表**               | **关键字段**                                                                       | **用途**           |
|----------------------|------------------------------------------------------------------------------------|--------------------|
| app_user             | id, nickname, password_hash, role, status, created_at                              | 用户与角色。       |
| user_training_policy | user_id, windows, daily_max, quiet_hours, retention_days, timezone                 | 用户仅可设置边界。 |
| push_subscription    | user_id, endpoint, p256dh, auth, user_agent, active                                | Web Push 订阅。    |
| training_session     | id, user_id, question_id, thread_id, stage, scheduled_at, exposed_at, completed_at | 一次突击会话。     |
| voice_attempt        | id, session_id, stage, round, audio_path, duration, upload_status                  | 每段语音。         |
| transcript_segment   | attempt_id, start_ms, end_ms, text, words_json, source                             | 时间戳转写。       |
| question             | id, source_bundle_id, prompt, type, target_defects, status, exposed_count          | 冻结题目。         |
| question_source      | id, title, publisher, url, level, published_at, accessed_at, snapshot_hash         | 来源元数据。       |
| source_claim         | id, source_id, claim_text, locator, excerpt, support_status, valid_until           | 事实原子。         |
| question_claim_map   | question_id, claim_id, usage_type                                                  | 题目事实映射。     |
| question_fingerprint | question_id, normalized_hash, embedding, structural_json, template_family          | 查重指纹。         |
| question_rubric      | question_id, version, dimensions_json, expected_elements, fatal_omissions          | 答题前冻结。       |
| evaluation_report    | session_id, logic_score, speech_score, adaptability_score, final_score, status     | 综合报告。         |
| evaluation_issue     | report_id, code, severity, confidence, quote, start_ms, end_ms, details            | 逐条问题证据。     |
| defect_definition    | code, name, description, detection_rule, score_cap                                 | 缺陷字典。         |
| defect_occurrence    | user_id, session_id, issue_id, defect_code, domain, confirmed                      | 单次出现。         |
| defect_profile       | user_id, defect_code, state, severity, frequency, recurrence, priority, confidence | 长期画像。         |
| appeal               | user_id, session_id, type, reason, status, resolution                              | 申诉与纠错。       |
| ai_job               | id, job_type, payload, status, retry_count, locked_at, error_code                  | 数据库任务队列。   |
| model_run            | job_id, provider, model, prompt_version, latency, tokens, structured_ok, trace_id  | AI 可观测性。      |
| prompt_version       | name, version, content_hash, schema_version, active                                | 提示词版本。       |
| weekly_report        | user_id, week_start, metrics_json, summary, created_at                             | 周度趋势。         |

## 14.2 关键唯一约束

- voice_attempt：UNIQUE(session_id, stage, round)。

- defect_occurrence：UNIQUE(session_id, issue_id, defect_code)。

- question_fingerprint.normalized_hash：唯一或可检测重复。

- training_session.thread_id：唯一。

- ai_job：同一业务操作使用 idempotency_key 唯一。

- 同一个 question_id 一旦 QUESTION_EXPOSED，就不得分配给任何用户再次使用。

# 15. API 规格

| **方法** | **路径**                                    | **说明**                                        |
|----------|---------------------------------------------|-------------------------------------------------|
| POST     | /api/v1/auth/login                          | 登录，返回 access/refresh token。               |
| POST     | /api/v1/invitations/accept                  | 邀请码注册。                                    |
| GET/PUT  | /api/v1/me/training-policy                  | 读取或更新允许时间边界。                        |
| POST     | /api/v1/push/subscriptions                  | 保存 Web Push 订阅。                            |
| GET      | /api/v1/trainings/current                   | 查询当前待接受或进行中的突击。                  |
| POST     | /api/v1/trainings/{id}/accept               | 接受通知并锁定题目。                            |
| POST     | /api/v1/trainings/{id}/expose               | 标记题目已播放；从此题目不可复用。              |
| GET      | /api/v1/trainings/{id}/state                | 获取阶段、倒计时、interrupt payload、处理进度。 |
| POST     | /api/v1/trainings/{id}/attempts             | 为指定 stage/round 幂等创建 attempt。           |
| PUT      | /api/v1/attempts/{id}/audio                 | 上传音频 multipart。                            |
| POST     | /api/v1/trainings/{id}/resume               | 提交 attempt_id，创建 GRAPH_RESUME 任务。       |
| GET      | /api/v1/trainings/{id}/report               | 读取最终报告。                                  |
| GET      | /api/v1/trainings/{id}/provenance           | 完成后读取来源与 Claim 映射。                   |
| PATCH    | /api/v1/attempts/{id}/transcript-correction | 仅提交 STT 纠错。                               |
| POST     | /api/v1/trainings/{id}/appeals              | 重复题、来源、转写或评审申诉。                  |
| GET      | /api/v1/me/defects                          | 个人缺陷画像。                                  |
| GET      | /api/v1/me/defects/{code}/occurrences       | 查看历史证据。                                  |
| GET      | /api/v1/me/weekly-reports                   | 周报告。                                        |
| DELETE   | /api/v1/me/trainings/{id}                   | 删除单条训练及音频。                            |
| DELETE   | /api/v1/me                                  | 删除账号和全部数据。                            |
| POST     | /api/v1/admin/invitations                   | 管理员创建邀请码。                              |
| GET      | /api/v1/admin/jobs/failed                   | 查看失败任务。                                  |
| GET      | /api/v1/health                              | 应用、数据库、存储和 provider 健康检查。        |

## 15.1 关键接口示例

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>POST /api/v1/trainings/{session_id}/resume<br />
{<br />
"stage": "FIRST_ANSWER",<br />
"attempt_id": "01J...",<br />
"idempotency_key": "session:first:1"<br />
}<br />
<br />
202 Accepted<br />
{<br />
"job_id": "01J...",<br />
"session_stage": "PROCESS_FIRST"<br />
}</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th>GET /api/v1/trainings/{session_id}/state<br />
{<br />
"stage": "WAIT_FOLLOWUP_AUDIO",<br />
"interrupt": {<br />
"type": "FOLLOWUP_QUESTION",<br />
"round": 1,<br />
"text": "你刚才认为……这个判断基于什么证据？",<br />
"answer_limit_seconds": 45<br />
},<br />
"version": 7<br />
}</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

# 16. AI Provider 与结构化输出

## 16.1 Provider 接口

| **Provider**      | **核心方法**                                                                                                        |
|-------------------|---------------------------------------------------------------------------------------------------------------------|
| LLMProvider       | generate_structured(...)；P0 实现 AliyunQwenProvider，模型由 QWEN\_\*\_MODEL 环境变量选择。                         |
| STTProvider       | transcribe(...) → Transcript；P0 实现 AliyunFunASRProvider，不加载本地模型。                                        |
| EmbeddingProvider | embed_texts(texts) → vectors；P0 实现 AliyunEmbeddingProvider（text-embedding-v4）。                                |
| SearchProvider    | search(query, domains, recency) → SearchResult\[\]。                                                                |
| ContentFetcher    | fetch(url) → 原始内容、类型、哈希。                                                                                 |
| TTSProvider       | synthesize(text) → audio；P0 实现 AliyunCosyVoiceProvider（cosyvoice-v3.5-plus），浏览器 speechSynthesis 可作降级。 |

## 16.2 结构化输出对象

| **对象**             | **关键字段**                                                                                         |
|----------------------|------------------------------------------------------------------------------------------------------|
| QuestionCandidate    | prompt, target_defects, claim_ids, fingerprint, expected_reasoning, prohibited_inferences。          |
| AnswerStructure      | direct_answer, facts_used, assumptions, unknowns, stakeholders, options, tradeoffs, risks, actions。 |
| LogicIssue           | code, severity, confidence, quote, start/end, explanation, missing_information, correction_rule。    |
| LogicReview          | dimension_scores, issues, strengths, score_caps, followup_strategy。                                 |
| EvidenceVerification | issue_id, evidence_valid, quote_match, timestamp_valid, correction。                                 |
| HistoricalMatch      | defect_code, similarity_type, occurrence_ids, common_pattern, confidence。                           |

## 16.3 提示词版本规则

- 任何提示词修改都必须创建新版本，保存 content_hash、输出 schema 版本和变更原因。

- 线上报告必须记录实际使用的 prompt_version、provider、model 和 model_run。

- 禁止在一个模型调用中同时完成出题、评分、历史匹配和写报告。

- 不保存或要求模型输出隐藏的完整思维链；只保存结论、依据、结构化问题和可审计证据。

- 关键评审使用“初评模型 + 独立证据复核”两步；可使用同一模型的独立上下文，但提示词必须分离。

# 17. 非功能需求

## 17.1 性能与容量

| **项**   | **P0目标**                                                                     |
|----------|--------------------------------------------------------------------------------|
| 用户规模 | 最多 4 个活跃账号；并发训练目标 2。                                            |
| 普通 API | 不含 AI 的接口 P95 \< 800ms。                                                  |
| 音频     | 单段最大 20MB，最长 180 秒。                                                   |
| AI处理   | 90 秒回答在参考环境下目标 120 秒内形成下一步或最终报告；超时显示进度并可恢复。 |
| 题目库存 | 每用户至少保有 7 道 READY 且未使用题目；不足时降低突击频率，不编造题。         |
| 数据库   | 题目数量低于数万时使用 pgvector 精确检索，暂不创建近似索引。                   |

## 17.2 安全与隐私

- 全站 HTTPS；密码使用 Argon2id 或 bcrypt；JWT 短期访问令牌 + 刷新令牌。

- 音频目录不对公网暴露；下载通过鉴权接口或短期签名地址。

- API Key 仅在服务端环境变量或秘密管理中保存；不得下发前端。

- 日志不得记录完整题目答案、原始音频地址、JWT、API Key 或来源受限内容。

- 用户可设置原始音频保留期并立即删除；删除账号时清理业务数据、向量、音频和 checkpoint。

- LangGraph checkpoint 可启用加密 serializer；密钥独立保存。

- 管理员默认无权查看其他用户正文与音频。

## 17.3 可观测性

| **对象**  | **必须记录**                                                                  |
|-----------|-------------------------------------------------------------------------------|
| HTTP      | request_id、user_id、path、status、duration，不记录敏感 body。                |
| AI调用    | provider、model、prompt_version、tokens、latency、structured_ok、error_code。 |
| LangGraph | thread_id、node、stage、checkpoint、retry、interrupt 类型。                   |
| 来源      | 搜索 query、URL、等级、抓取状态、snapshot_hash、Claim 支持状态。              |
| 查重      | 最相似题、各级相似度、终审结论和拒绝原因。                                    |
| 评审      | issue、evidence verifier 结果、封顶规则和申诉状态。                           |

## 17.4 备份与保留

- PostgreSQL 每日备份，至少保留 7 个日备份和 4 个周备份。

- 音频按用户保留策略清理；清理任务必须先标记、后删除，并记录 audit log。

- 题目、Rubric、来源元数据、Prompt 版本和评审证据长期保留，直到用户删除账号。

- 备份恢复至少每月验证一次。

# 18. 验收标准

| **编号** | **验收条件**                                                         |
|----------|----------------------------------------------------------------------|
| AC-01    | 用户无法选择题目类型、缺陷、领域和难度。                             |
| AC-02    | 系统能在允许窗口随机发起通知；未接受不扣分。                         |
| AC-03    | 第一次回答不能覆盖，且可回放。                                       |
| AC-04    | 一次会话至少完成第一答、1 次追问和最终答；退出可恢复或按规则作废。   |
| AC-05    | 每个题目事实均能定位来源和证据；unsupported_claim_count=0。          |
| AC-06    | 与历史题完全一致、同义改写或明显换皮的候选题被拦截。                 |
| AC-07    | 用户标记重复后，本题不计分且模板家族禁用。                           |
| AC-08    | 每条逻辑问题包含 defect_code、原话、时间点、原因、缺失信息、置信度。 |
| AC-09    | 逻辑、口语和应变三个分数独立展示。                                   |
| AC-10    | Python 封顶规则能覆盖“答非所问但语言流畅”的情况。                    |
| AC-11    | 同一缺陷至少出现 3 次、跨 2 场景后才确认为稳定缺陷。                 |
| AC-12    | 历史相似问题说明相似的是场景、缺陷还是根因。                         |
| AC-13    | 用户能纠正 STT，但不能重写答案。                                     |
| AC-14    | 用户可以申诉来源、重复、转写和评审。                                 |
| AC-15    | 删除账号后，音频、业务记录、向量和 checkpoint 均不可恢复地清除。     |
| AC-16    | 模型或来源服务失败时，不生成无依据题目，不丢失会话状态。             |

# 19. 风险与边界

| **风险**            | **影响**                     | **缓解措施**                                                       |
|---------------------|------------------------------|--------------------------------------------------------------------|
| AI评分不稳定        | 同一回答分数漂移或误判。     | 冻结 Rubric、结构化输出、硬规则、证据复核、Golden Set 回归、申诉。 |
| 题目“换皮”          | 用户形成应试套路。           | 四级查重、同事件禁用、结构维度变化、用户最终裁决。                 |
| 来源事实错误或过期  | 训练建立在错误背景上。       | 来源等级、有效期、抓取哈希、多来源冲突披露、失败关闭。             |
| 转写错误            | 逻辑评审被错误文本影响。     | 保留原音频、允许有限纠错、低置信词标记、必要时重转。               |
| 用户依赖模板        | 说出框架但没有实际判断。     | 空泛框架封顶、追问具体目标/证据/取舍、跨场景迁移。                 |
| 通知疲劳            | 用户关闭通知或逃避训练。     | 每日默认 1 次、时间边界、疲劳系数、延期一次。                      |
| 隐私泄漏            | 工作和团队信息暴露。         | 短期音频保留、最小日志、私有存储、用户删除、Provider 隐私提示。    |
| LangGraph副作用重复 | 恢复后重复创建记录或发通知。 | interrupt 前副作用幂等、独立节点、唯一约束。                       |

# 20. 技术参考资料

下列资料仅用于说明技术选择和实现边界；项目应在锁定依赖版本时再次核对官方变更。

**\[R1\]** [<u>LangGraph Overview - low-level orchestration, durable execution and HITL</u>](https://docs.langchain.com/oss/python/langgraph/overview)

**\[R2\]** [<u>LangGraph Interrupts - pause, resume, thread_id and idempotent side effects</u>](https://docs.langchain.com/oss/python/langgraph/interrupts)

**\[R3\]** [<u>LangGraph Persistence and Checkpointers</u>](https://docs.langchain.com/oss/python/langgraph/persistence)

**\[R4\]** [<u>LangGraph Checkpointers - PostgresSaver and durability modes</u>](https://docs.langchain.com/oss/python/langgraph/checkpointers)

**\[R5\]** [<u>FastAPI Features - OpenAPI, validation, security and WebSocket support</u>](https://fastapi.tiangolo.com/features/)

**\[R6\]** [<u>MDN MediaRecorder API</u>](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder)

**\[R7\]** [<u>Web Push Notifications Overview</u>](https://web.dev/articles/push-notifications-overview)

\[R8\] 阿里云百炼模型大全 - fun-asr、cosyvoice-v3.5-plus、text-embedding-v4

**\[R9\]** [<u>pgvector - vector similarity search for PostgreSQL</u>](https://github.com/pgvector/pgvector)

\[R10\] 阿里云百炼文本生成 - Qwen3.5 / Qwen3.6 结构化输出

\[R11\] 阿里云百炼 text-embedding-v4

\[R12\] 阿里云百炼首次调用千问 API - DASHSCOPE_API_KEY 与 OpenAI 兼容接口

\[R13\] OpenAI Codex CLI、AGENTS.md、配置与最佳实践官方文档

# 附录 A. 云端模型与环境变量规格

## A.1 技术决策

| 冻结决策：P0 运行时全部使用阿里云百炼线上模型。应用服务器只运行 Vue3、FastAPI、LangGraph、Worker、Scheduler、PostgreSQL 和文件处理代码，不部署本地推理模型，不要求 GPU。 |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

- 模型供应商通过 Provider 接口隔离，但 P0 的唯一正式实现为阿里云百炼。

- 对话与评审模型限定为 qwen3.5-plus 或 qwen3.6-plus；默认 qwen3.6-plus，降级 qwen3.5-plus。

- 模型 ID 不得出现在 LangGraph 节点、Prompt 或业务规则中，只能从 Settings 读取。

- 所有 API Key 仅存在于后端运行环境；前端构建产物和 VITE\_\* 环境变量不得包含任何模型密钥。

- 云模型不可用时，系统暂停对应任务并保留状态；不得临时切换为无来源编题或跳过证据复核。

## A.2 模型职责矩阵

| **能力**           | **环境变量**           | **P0 默认值**       | **职责**                                                   |
|--------------------|------------------------|---------------------|------------------------------------------------------------|
| 动态对话/追问      | QWEN_DIALOG_MODEL      | qwen3.6-plus        | 生成单个针对性追问、最终口头提示；低温度，避免替用户作答。 |
| 题目与 Rubric 生成 | QWEN_QUESTION_MODEL    | qwen3.5-plus        | 基于 VERIFIED Claim 生成候选题和隐藏评分蓝图。             |
| 严格逻辑评审       | QWEN_REVIEW_MODEL      | qwen3.6-plus        | 回答结构提取、逻辑初评和复杂管理/系统视角判断。            |
| 证据独立复核       | QWEN_VERIFY_MODEL      | qwen3.6-plus        | 检查每条批评是否被逐字稿和时间点支持；独立上下文执行。     |
| 故障降级           | QWEN_FALLBACK_MODEL    | qwen3.5-plus        | 主模型超时、限流或结构化输出失败后的受控降级。             |
| 语音识别           | ALIYUN_ASR_MODEL       | fun-asr             | 录音完成后异步转写，返回可定位时间戳。                     |
| 语音合成           | ALIYUN_TTS_MODEL       | cosyvoice-v3.5-plus | AI 问题和追问语音播报。                                    |
| 向量化             | ALIYUN_EMBEDDING_MODEL | text-embedding-v4   | 历史题语义查重、缺陷候选召回。                             |

## A.3 服务端环境变量契约

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th># 运行模式<br />
APP_ENV=dev<br />
AI_PROVIDER=aliyun<br />
AI_PROVIDER_MODE=aliyun # 本地测试可临时使用 mock<br />
<br />
# 阿里云百炼：仅服务端读取<br />
DASHSCOPE_API_KEY=<br />
DASHSCOPE_BASE_URL=https://&lt;WorkspaceId&gt;.cn-beijing.maas.aliyuncs.com/compatible-mode/v1<br />
<br />
# Qwen 模型路由<br />
QWEN_DIALOG_MODEL=qwen3.6-plus<br />
QWEN_QUESTION_MODEL=qwen3.5-plus<br />
QWEN_REVIEW_MODEL=qwen3.6-plus<br />
QWEN_VERIFY_MODEL=qwen3.6-plus<br />
QWEN_FALLBACK_MODEL=qwen3.5-plus<br />
<br />
# 云端语音与向量<br />
ALIYUN_ASR_MODEL=fun-asr<br />
ALIYUN_TTS_MODEL=cosyvoice-v3.5-plus<br />
ALIYUN_EMBEDDING_MODEL=text-embedding-v4<br />
<br />
# 调用策略<br />
LLM_TIMEOUT_SECONDS=120<br />
LLM_MAX_RETRIES=2<br />
LLM_TEMPERATURE_DIALOG=0.2<br />
LLM_TEMPERATURE_QUESTION=0.7<br />
LLM_TEMPERATURE_REVIEW=0.0<br />
QWEN_ENABLE_THINKING_QUESTION=true<br />
QWEN_ENABLE_THINKING_REVIEW=true<br />
QWEN_ENABLE_THINKING_DIALOG=false<br />
<br />
# 可选：ASR 需要临时可访问音频 URL 时使用私有 OSS<br />
ALIYUN_OSS_ENDPOINT=<br />
ALIYUN_OSS_BUCKET=<br />
ALIYUN_OSS_ACCESS_KEY_ID=<br />
ALIYUN_OSS_ACCESS_KEY_SECRET=<br />
ALIYUN_OSS_SIGNED_URL_TTL_SECONDS=900</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

| 仓库只提交 .env.example，真实 .env 必须加入 .gitignore。推荐将真实密钥存入操作系统环境变量或仓库外的 secrets 文件；Codex CLI 不得读取、打印或修改真实 .env。 |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------|

## A.4 配置加载与启动校验

| **检查项** | **规则**                                                                      | **失败行为**                                |
|------------|-------------------------------------------------------------------------------|---------------------------------------------|
| 必填密钥   | AI_PROVIDER_MODE=aliyun 时 DASHSCOPE_API_KEY 和 DASHSCOPE_BASE_URL 必填。     | API/Worker 启动失败并给出脱敏错误码。       |
| 模型 ID    | 所有 QWEN\_\*、ASR、TTS、Embedding 模型必须为非空字符串。                     | 禁止回退到代码中的隐式默认值。              |
| URL        | Base URL 必须为 HTTPS，且不包含未替换的 \<WorkspaceId\>。                     | 启动失败。                                  |
| 日志脱敏   | SecretStr、Authorization、OSS Secret 不得进入日志和 model_run。               | 测试失败；阻止发布。                        |
| 连通性     | 开发/发布检查执行一次 LLM、ASR、TTS、Embedding smoke test。                   | 将 Provider 标为 DEGRADED；不开始正式突击。 |
| 模型记录   | 每次调用记录 provider、model、request_id、latency、tokens/字符/秒数和错误码。 | 记录失败不影响原任务状态，但必须产生告警。  |

## A.5 Provider 边界

- FastAPI 路由和 LangGraph 节点不得直接 import 阿里云 SDK；只能依赖 LLMProvider、STTProvider、TTSProvider、EmbeddingProvider。

- AliyunQwenProvider 可使用 OpenAI Python SDK 连接百炼 compatible-mode/v1；阿里云特有参数由 Provider 的 extra_body 映射。

- 语音、TTS 与 Embedding 的接口差异封装在对应 Provider 中，业务层只接收 Pydantic 结构。

- 测试必须提供 Mock Provider 和录制好的固定响应，单元测试不得消耗真实 API。

- 模型切换只修改 .env 并重启对应进程，不修改 Prompt、Graph 或 domain 规则。

## A.6 数据与密钥安全

- 真实录音可能包含公司、客户和团队信息；上传云模型前必须记录用户授权与保留策略。

- 使用 OSS 时 Bucket 必须私有，仅生成短时签名 URL；URL 不写入长期日志。

- DASHSCOPE_API_KEY、OSS Secret、JWT、VAPID、LANGGRAPH_AES_KEY 均视为同等级秘密。

- 任何错误响应持久化前先移除请求头、密钥和完整私有音频 URL。

- 用户删除训练记录时，同时删除本地/OSS 音频、转写、向量、评审证据和相关 checkpoint。

## A.7 验收标准

- 代码仓库搜索不到真实 API Key，前端产物中不存在 DASHSCOPE_API_KEY。

- 仅修改 QWEN_DIALOG_MODEL 即可切换对话模型，无须修改业务代码。

- 关闭外网或使用无效密钥时，任务进入可重试失败，不生成伪造报告。

- 不安装本地模型依赖、不下载模型权重，CPU 服务器可完成全部业务服务启动。

- 四类 Provider 均有 mock 合约测试和真实 smoke test 脚本。

# 附录 B. Codex CLI 开发协作规格

## B.1 定位

| Codex CLI 是开发执行工具，不是产品运行时组件。Codex 可以读取 SPEC/SOP、修改仓库代码、运行测试和审查 diff，但不能替代产品验收、真实模型密钥管理和人工合并决策。 |
|----------------------------------------------------------------------------------------------------------------------------------------------------------------|

- 一次 Codex 任务只对应一个明确阶段或一个可验收缺陷，禁止用单条提示生成整个系统。

- 复杂任务必须先进入 Plan 模式，输出受影响文件、迁移、测试和风险，再开始编码。

- 每次任务必须给出 Goal、Context、Constraints、Out of scope、Done when。

- Codex 完成代码后必须运行指定测试并执行独立 review；未通过时不得标记完成。

- Codex 不得自动提交、推送、修改真实 .env、删除用户数据或执行生产部署，除非用户针对该次操作显式授权。

## B.2 指令层级

| **文件**                              | **作用**           | **建议内容**                                           |
|---------------------------------------|--------------------|--------------------------------------------------------|
| ~/.codex/AGENTS.md                    | 个人全局规则       | 中文回答、先计划、不得访问秘密、默认测试与 review。    |
| 仓库根 AGENTS.md                      | 整个项目固定规则   | 产品 P0 原则、架构边界、命令、Definition of Done。     |
| apps/web/AGENTS.md                    | 前端局部规则       | PWA、录音、权限、类型检查、移动端验收。                |
| services/backend/AGENTS.md            | 后端局部规则       | FastAPI、SQLAlchemy、Provider、迁移、测试和安全。      |
| services/backend/app/graphs/AGENTS.md | LangGraph 局部规则 | State 小型化、interrupt、幂等、checkpoint 与恢复测试。 |
| docs/tasks/Pxx.md                     | 单次任务合同       | 本阶段范围、验收、禁止项、需运行命令。                 |

## B.3 安全与权限默认值

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr class="header">
<th># ~/.codex/config.toml<br />
model = "gpt-5.5"<br />
approval_policy = "on-request"<br />
sandbox_mode = "workspace-write"<br />
web_search = "cached"<br />
<br />
[windows]<br />
sandbox = "elevated"</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

- 默认使用 on-request + workspace-write；不要在日常开发中使用 --yolo 或 danger-full-access。

- 需要联网核对依赖或官方 API 时，可针对单次任务启用搜索，并要求把依据写入 ADR 或任务报告。

- 真实 .env 保持在 Git 忽略范围，AGENTS.md 明确禁止 Codex 读取或输出其内容。

- 同一工作树只运行一个会修改代码的 Codex 会话；并行任务必须使用独立 git worktree 且文件范围不重叠。

## B.4 Codex 任务验收

- 任务只修改授权范围内的文件，无无关重构和依赖膨胀。

- 新增行为有测试；数据库变更有 Alembic；Prompt/Schema 变更有 Golden Case。

- Codex 已运行 lint、type-check、unit/integration tests，并在结果中报告真实命令和退出状态。

- 使用 /review 审查未提交变更，严重问题清零后再人工提交。

- 任务完成时更新 docs/progress.md 或对应任务文件，记录完成项、剩余风险和下一阶段入口。

## B.5 Codex 官方依据

- Codex CLI 官方文档：本地读取、修改并运行所选目录中的代码。

- AGENTS.md 官方文档：Codex 在工作前加载全局、仓库和子目录指令，越靠近当前目录的规则优先。

- Codex 最佳实践：复杂任务先计划；提示包含 Goal、Context、Constraints、Done when；完成后测试并 review。

- Codex 配置文档：推荐从 approval_policy=on-request、sandbox_mode=workspace-write 开始。

- Codex CLI review：可审查未提交修改、某个提交或相对基线的 diff，不修改工作树。

# 附录 C. Python 依赖与锁定规格

## C.1 运行时基线

| 项目 | 固定值 | 约束目的 |
|---|---|---|
| Python 系列 | `>=3.12,<3.13` | 防止未经验证切换 Python 大/小版本。 |
| Python 补丁版本 | `3.12.13` | 本地、CI、容器优先使用同一补丁版本。 |
| uv | `0.11.23` | 保持解析与锁文件行为一致。 |
| 直接依赖事实源 | `services/backend/pyproject.toml` | 所有直接依赖使用精确版本 `==`。 |
| 完整依赖图 | `services/backend/uv.lock` | 锁定传递依赖与文件哈希；P00 真实生成后提交。 |

## C.2 直接依赖基线

| 类别 | 依赖与精确版本 |
|---|---|
| API 与配置 | FastAPI 0.138.0；Uvicorn 0.49.0；Pydantic 2.13.4；pydantic-settings 2.14.2 |
| 数据库 | SQLAlchemy 2.0.51；Alembic 1.18.4；asyncpg 0.31.0；psycopg 3.3.4；pgvector 0.4.2 |
| 编排 | langchain-core 1.4.8；LangGraph 1.2.6；langgraph-checkpoint-postgres 3.1.0 |
| 云模型与存储 | openai 2.43.0；dashscope 1.25.23；oss2 2.19.1 |
| 抓取与文档 | httpx 0.28.1；trafilatura 2.1.0；PyMuPDF 1.27.2.3 |
| 调度与可靠性 | APScheduler 3.11.2；tenacity 9.1.4；aiofiles 25.1.0；python-multipart 0.0.32 |
| 认证与推送 | PyJWT 2.13.0；pwdlib 0.3.0；email-validator 2.3.0；pywebpush 2.3.0 |
| 测试与质量 | pytest 9.1.1；pytest-asyncio 1.4.0；pytest-cov 7.1.0；Ruff 0.15.18；Mypy 2.1.0；RESPX 0.23.1；time-machine 3.2.0；pre-commit 4.6.0 |

完整机器可读清单以 `services/backend/pyproject.toml` 为准。

## C.3 LangGraph 与 LangChain 依赖边界

- 本项目使用 `langgraph` 作为低层、有状态、可暂停恢复的工作流编排器，业务主流程由明确的 `StateGraph` 节点与条件边控制。
- `langchain-core==1.4.8` 作为 LangGraph 的基础运行依赖被显式固定，以便在直接依赖清单中可见、可审计；它不是完整 `langchain` Agent 框架。
- P0 有意不安装完整 `langchain` 和 `langchain-openai`：阿里云 Qwen 通过 OpenAI 兼容 SDK / DashScope SDK 和自定义 Provider 调用，结构化输出由 Pydantic 约束。
- P0 不使用 `langchain.agents`、预构建 Agent 或 LCEL 替代领域规则；来源门槛、防重复、评分封顶和缺陷确认仍由确定性 Python 代码负责。
- 后续确需引入完整 LangChain 时，必须建立独立 ADR，说明当前方案不足、引入范围、额外传递依赖、回归测试和回滚方式。

## C.4 约束规则

- 本项目是应用而非公共库，直接依赖采用精确版本；升级必须显式进行。
- `uv.lock` 不得被忽略，不得手写，不得由 Codex 在普通功能任务中批量刷新。
- CI 必须运行 `uv lock --check` 与 `uv sync --locked --all-groups`。
- 新增或升级依赖必须单独说明用途、替代方案、许可证、传递依赖、测试和回滚。
- 未经批准禁止本地模型和 GPU 依赖，包括 torch、transformers、faster-whisper、funasr、modelscope、vLLM 和 CUDA/ROCm 组件。
- 版本基线核对日期为 2026-06-20；版本不是“永久最新”，后续必须按依赖升级 SOP 更新。

## C.5 验收

- `scripts/verify_dependency_policy.py` 校验 Python/uv 基线、精确版本和禁止依赖。
- P00 完成时，`pyproject.toml`、`.python-version` 和真实生成的 `uv.lock` 必须全部提交。
- 锁文件产生无关大面积变化时，任务失败并回退。

