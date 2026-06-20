# ADR-002：LangGraph standalone，不引入完整 LangChain

- 状态：Accepted
- 版本：v1.0
- 日期：2026-06-20

## 背景

系统需要可暂停、恢复、持久化、条件分支和并行评审的语音训练工作流，同时要求评分、来源门槛、查重阈值与状态转换保持确定性和可审计。

## 决策

1. 使用 `langgraph==1.2.6` 和 `langgraph-checkpoint-postgres==3.1.0`。
2. 显式固定 `langchain-core==1.4.8`，作为 LangGraph 的基础运行兼容边界。
3. P0 不安装完整 `langchain` 元包，也不安装 `langchain-openai`。
4. 模型调用由自定义 Provider + `openai` / `dashscope` SDK 完成；结构化输出由 Pydantic 约束。
5. 不使用 `langchain.agents`、预构建 Agent 或 LCEL 替代领域硬规则。

## 原因

- LangGraph 官方明确说明可在不使用完整 LangChain 的情况下独立运行。
- 当前系统需要受控状态机，而不是通用自由 Agent 框架。
- 减少额外抽象和依赖，便于追踪模型调用、复现评审和定位故障。
- 显式固定 `langchain-core` 可以在生成 `uv.lock` 前明确关键兼容边界。

## 后果

- LangGraph 节点需显式调用项目 Provider。
- 不直接复用完整 LangChain 的 Agent、Chain 和模型包装器。
- 后续确需完整 LangChain 时，必须建立新 ADR、单独审批依赖并完成图恢复、Prompt/Schema 和 Golden Case 回归。

## 官方依据

- https://docs.langchain.com/oss/python/langgraph/overview
- https://docs.langchain.com/oss/python/langgraph/install
- https://pypi.org/project/langgraph/
