# LangGraph 局部规则

- 本目录只使用 LangGraph `StateGraph`、interrupt/resume、Checkpoint 与自定义 State；不使用 `langchain.agents` 或完整 LangChain Agent 框架。
- 只使用 `StateGraph` 明确声明节点、边和条件路由；不要创建可自由选择工具的自治 Agent。
- 每个节点必须声明输入、输出、外部副作用、重试策略、错误码和幂等键。
- `interrupt()` 节点恢复时会从节点开头重放，因此副作用必须拆到前置幂等节点。
- 一个训练 session 对应一个稳定 `thread_id`；不同训练不得复用无限增长线程。
- Checkpointer 保存流程状态；缺陷画像、题目、来源、评审、音频元数据必须写业务表。
- State 不保存音频、网页、PDF、Embedding 全量和数据库连接对象。
- 图节点只调用 domain/service/provider；评分封顶、查重阈值和来源门槛不得写进 Prompt。
- 必须覆盖：正常流程、每个 interrupt/resume、API/worker 重启、重复 resume、STT 失败、来源失效和幂等恢复测试。
