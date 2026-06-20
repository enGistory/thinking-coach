# v1.0 初始开发基线

发布日期：2026-06-20

本版本是项目尚未开始编码前的统一初始基线，所有前期讨论稿均合并归一为 v1.0。

主要内容：

- 完整 SPEC、SOP、P00-P11 任务合同与 Codex CLI 协作规则；
- Python 3.12.13、uv 0.11.23、精确直接依赖和 uv.lock 治理；
- 阿里云线上 LLM、ASR、TTS、Embedding Provider 架构；
- LangGraph StateGraph + Postgres Checkpointer 编排；
- 显式固定 `langchain-core==1.4.8`，但有意不安装完整 `langchain` / `langchain-openai`；
- 真实来源、永不重复、证据化评审和个人缺陷画像规则；
- 尚未附带 uv.lock，需在 P00 中真实解析生成。
