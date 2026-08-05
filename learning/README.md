# ContextGate — 面试向学习笔记

> 目标：能讲清关键模块逻辑（白板 + 指代码）。  
> 证据来源：codebase-memory 图 + 源码；不依赖已删旧稿。

## 文档

| 文件 | 内容 |
|------|------|
| [00-interview-map.md](00-interview-map.md) | 三维总览：图 / 面试官 / 求职者 |
| [04a-auth-rbac.md](04a-auth-rbac.md) | **深挖 A**：API Key、四角色、scope、签名、密码换 key |
| [05b-pipeline-nodes.md](05b-pipeline-nodes.md) | **深挖 B**：DAG 全节点、条件边、早退与演进 |
| [07c-harness-cost-shortpath.md](07c-harness-cost-shortpath.md) | **深挖 C**：短路径、成本、LLMHarness、key failover |
| [09d-rag-capability.md](09d-rag-capability.md) | **深挖 D**：RAG 缓存/检索 vs Capability Hub invoke |
| [12o-observability.md](12o-observability.md) | **可观测**：LangFuse / Prometheus / 审计 + 怎么看指标 |

## 建议顺序

1. 读完 `00`  
2. **A → B → C**，穿插 **D**；收尾读 **可观测**（怎么用 trace_id 定位）  
3. 自测：四角色各打一枪 + 长路径打开 LangFuse + `curl /metrics`
