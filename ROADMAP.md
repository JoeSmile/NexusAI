# Roadmap

> ContextGate 发展路线图。当前在 **v1.0** 阶段。

---

## v1.0 — 核心管线（当前 Phase）

**目标:** 从 emotional_chat demo 改造为可观测、可审计、安全的企业级 LLM 管线网关

**17 个 Task / 71 个 Subtask**，详见 `tasks/` 目录。

| 领域 | Task |
|------|------|
| Rebranding | 00 |
| 存储 (pgvector) | 01 |
| 认证 + RBAC0 + 审批 | 02 |
| 多租户 + 审计 | 03 |
| LangGraph 管线 | 04 |
| LangFuse 可观测 | 05 |
| 缓存系统 | 06 |
| Harness + 成本 + Skill | 07 |
| 安全护栏 | 09 |
| 文件上传加固 | 10 |
| 断路器 + 降级 | 11 |
| 健康检查 + SLA + 错误码 | 12 |
| Seed 数据 | 13 |
| Docker + uv | 14 |
| CI/CD | 15 |
| 生产部署 | 16 |
| 项目占领 | 17 |

**标志:** 全链路 trace 在 LangFuse 可见，安全护栏 P0+P1 全部就位

---

## v1.1 — RAG 深化

### 多路召回

- **pgvector retriever** — 语义向量 ANN 检索（已有基础）
- **Neo4j retriever** — 知识图谱检索（实体关系查询）
- **全文检索** — PostgreSQL `tsvector` 全文搜索
- **多路融合** — `Reciprocal Rank Fusion` 合并各路结果

### 检索增强

- **HyDE** — 先生成假想文档再检索（调一次小模型，花几毛钱）
- **ReRank** — 用本地 `bge-reranker` 或 LLM 重排序
- **查询改写** — 扩写/纠错/意图补全

### 评估

- **黄金测试集** — `data/test/rag_test_set.yaml`
- **评估脚本** — `scripts/eval_rag.py`（Recall / Precision / Latency / MRR）
- **回归门禁** — CI 里 PR 提交自动跑 RAG 评估，精度下降不让合

### 文档管理

- **文档上传 API** — `POST /api/documents` 上传 PDF/docx/md，自动 chunk + embedding
- **文档列表/删除** — `GET/DELETE /api/documents`
- **增量更新** — `POST /api/documents/reindex` 重建全部 embedding

**结构预留:**

```
backend/core/retrieval/
├── registry.py      ← 检索器注册 + 多路融合
├── base.py          ← BaseRetriever 抽象
├── pgvector.py      ← pgvector ANN（Task 01 的 vector_ops 搬过来）
├── neo4j.py         ← Neo4j 图谱查询（v1.1 实现）
├── fulltext.py      ← PostgreSQL tsvector（v1.1 实现）
└── reranker.py      ← ReRank（v1.1 实现）
```

**标志:** RAG 评估脚本通过，多路召回 recall > 0.85

---

## v1.2 — Web 管理 UI

### 管理后台

- API Key 管理页面（创建/吊销/查看消费量）
- 审计日志查询 + 导出
- 健康状态仪表盘
- 审批流程页面（查看待审批 / 通过 / 拒绝）
- 文档管理页面（上传/删除/重建索引）

### Playground

- 现有 `playground.html` 升级为完整开发者工具
- 请求历史 + 响应对比
- curl 命令一键复制

**标志:** 不需要 curl 也能完成日常管理操作

---

## v2.0 — ai-platform 集成

### 架构

```
ai-platform (管理面)
├── 多应用管理 (情绪 bot / 知识库 QA / 报告生成)
├── 工作流编排 (拖拽 pipeline 节点)
├── 知识库管理 UI
├── Agent 生命周期 (INACTIVE/ENABLED/DISABLED/DELETED)
├── 租户/用户管理
├── 审批流程 UI
├── 成本仪表盘 (按日/按应用/按租户)
└── 报价/计费模拟

ContextGate (运行时)
├── 不变，所有 AI 请求经过这里
└── 暴露 Pipeline 注册 API 给 ai-platform:
    POST /api/pipelines
    { app_id, nodes, routing, guardrails, models }
```

### 关键接口

| 接口 | 说明 |
|------|------|
| `POST /api/pipelines` | ai-platform 注册 pipeline 定义 |
| `GET /api/traces` | ai-platform 读取 trace 数据 |
| `GET /api/cost/summary` | ai-platform 读取成本报表 |
| `POST /api/admin/approve` | ai-platform 调用审批 |

**标志:** ai-platform 可以零代码创建一个新的 AI 应用

---

## 长期方向

| 方向 | 说明 |
|------|------|
| **插件市场** | 第三方 Skill 通过 GitHub 仓库安装 |
| **模型代理** | 统一管理多个 LLM Provider（Deepseek / OpenAI / 本地 vLLM） |
| **联邦审计** | 多租户审计日志统一汇到监管端 |
| **安全攻防** | 红队测试 + 自动加固 prompt 注入规则 |
| **边缘部署** | 轻量版本跑在国产化服务器上（ARM / 信创 OS） |
