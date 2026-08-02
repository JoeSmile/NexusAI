# QA — Demo 剧本(CIO 向,10-15 分钟)

> 来源: `docs/MANUAL_TEST.md` §12。价值主线: 可审计、可溯源、全链路可控、成本可见。

| 步 | 演示 | 端点/页面 | 价值点 |
|----|------|-----------|--------|
| 1 | 登录与权限 | 无 key → 401;user key → /chat 通;admin key → 管理页 | 企业级认证,四角色隔离 |
| 2 | 意图识别 | intent.html 输入企业问题 → knowledge_query + 置信度 | 智能分流,长路径才花钱 |
| 3 | 知识库问答 | rag.html 问「信息安全管理制度」→ 引用回答 | 内部知识资产变现 |
| 4 | 流式体验 | streaming.html 长文逐字输出 | 体验 + 可中断(成本可控) |
| 5 | 审计溯源 | audit logs 搜刚才的 trace_id | 全链路可审计,合规刚需 |
| 6 | 成本治理 | admin llm-keys + cost-summary | 每笔调用成本可算,CIO 最关心 |
| 7 | 可观测 | LangFuse UI span 树 | 出问题 30 秒定位到节点 |
| 8 | 缓存降本 [T29] | 同一问题连问 3 次,第 2/3 次秒回 cache_hit=true;status 命中率上升 | 重复问题零成本——员工反复问同一制度不再烧钱 |

## 排练建议

- Demo 前置: `LLM_PROVIDER=record make run` 先采一轮真实数据转 replay,避免现场波动
- 第 8 步是 Task 29 新增卖点,建议排在第 6 步成本治理之后,形成"成本可见 → 成本可降"的闭环叙事
- 演示前用 `examples/qa/01-smoke/smoke_qa.sh` 快速确认环境存活
