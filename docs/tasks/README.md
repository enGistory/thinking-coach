# Codex 任务顺序

1. [P00 工程骨架与约束](P00-bootstrap.md)
2. [P01 阿里云云模型配置与 Provider](P01-cloud-providers.md)
3. [P02 数据库、账号与隔离](P02-database-auth.md)
4. [P03 语音录制、上传与回放纵向切片](P03-audio-slice.md)
5. [P04 云端转写与口语指标](P04-transcription-metrics.md)
6. [P05 LangGraph 语音答辩闭环](P05-langgraph-session.md)
7. [P06 严格证据化评审](P06-evaluation.md)
8. [P07 个人缺陷经验库与训练画像](P07-defect-memory.md)
9. [P08 真实来源、事实原子与自动出题](P08-source-question.md)
10. [P09 题目永不重复与换皮拦截](P09-never-repeat.md)
11. [P10 自适应随机突击与推送](P10-random-strike.md)
12. [P11 报告、隐私、部署与发布验收](P11-release.md)

每个任务使用独立分支和新的 Codex 会话；只有同一任务修复才使用 `codex resume --last`。
