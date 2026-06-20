# Architecture Decision Records

建议至少建立：
- ADR-001：采用 Vue3 PWA 而非原生 App。
- ADR-002：采用 LangGraph StateGraph 固定工作流；已接受，见 `ADR-002-langgraph-standalone.md`。
- ADR-003：采用 PostgreSQL `ai_job` 任务队列。
- ADR-004：全部运行时模型使用阿里云线上 API，不部署本地模型。
- ADR-005：业务数据库为事实源，LangGraph Checkpoint 仅保存流程状态。
