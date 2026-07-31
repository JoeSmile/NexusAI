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

### 威胁情报 + 自动拉黑

> 现在 guardrails 只是无状态拦截（来一次拦一次）。v1.1 加记仇机制，累积攻击行为后自动拉黑。

- **ThreatIntel 模块** — 每请求记分板（key_hash + offense_type + count）
- **三级响应:**
  - `SUSPICIOUS`（1 次）→ 记日志，不处理
  - `WATCHED`（2 次）→ 每次请求慢 500ms 惩罚，写审计告警
  - `BLOCKED`（3 次）→ `api_keys.is_active = false`，自动拉黑
- **触发源:** guardrails 拦截（注入/PII/违规）、rate_limiter 超限
- **auth_check 集成:** pipeline 入口先查 threat_intel，拉黑的直接 403
- **管理 API:** `GET /api/admin/threats` 查看拉黑列表，`POST /api/admin/threats/{id}/release` 解封

**结构预留:**

```
backend/core/threat_intel/
├── __init__.py
├── scorer.py         ← 记分 + 分级判断
├── rules.py          ← 什么行为记几分
└── api.py            ← 管理 API
```

### 反思引擎 ReflectionEngine（可配置 BERT / LLM）

> 流式模式下用户已经看到了答案，所以全量反思不是"阻止当前回答"，而是撤回机制 + 质量审计层。
> 后端是可配置的：配了 BERT 用 BERT，配了便宜 LLM 用 LLM，都没配就关闭。

- **ReflectionEngine 接口** — `backend/core/guardrails/reflector.py`
  - 配置 `BERT_API_URL` → 本地 BERT 反射（快、便宜）
  - 配置 `REFLECT_MODEL` → 便宜 LLM 反射（语义级）
  - 都不配 / `REFLECT_ENABLED=false` → 关闭
- **三项检查:**
  - 意图一致性（回答是否偏离用户 Query）
  - 幻觉实体检测（提取实体 → 查知识库）
  - 违规内容（语义级，补充正则的盲区）
- **两种落地方式:**
  - **撤回机制:** 反思失败 → SSE 发 `{"type":"retraction"}`，前端撤回显示
  - **质量审计:** 反思结果写 LangFuse + audit，标注 `hallucination_risk`，喂给后续评估

**依赖 v1.0 已有的:**
- SSE retraction 事件类型（v1.0 Subtask 02.06 已加）
- guardrails_output 节点（v1.0 Task 09 已有）

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

## 小模型挂载点清单（Model Mount Points）

> **背景:** 本项目多处使用小模型，v1.0 阶段全部 mock/降级。后期在另一台 Windows 机器上跑真实小模型（vLLM / Ollama / BERT 服务），本机通过 HTTP 调用。
>
> **核心原则:** 所有小模型走 **OpenAI 兼容接口**，配置化切换（Mac 上 mock，Windows 上真模型），代码零改动。

### 挂载点总览

| # | 挂载点 | 用途 | v1.0 现状 | v1.1+ 真模型 | 配置项 |
|---|--------|------|----------|-------------|--------|
| 1 | **Embedding** | 向量化文本（记忆/知识库） | `embed_text()` API 优先，无 key 回退哈希向量 | `bge-m3` / `text-embedding-3-small` (vLLM) | `EMBEDDING_MODEL` + `LLM_BASE_URL` |
| 2 | **意图识别** | 分类用户意图（greeting/advice/query/...） | 大模型 JSON 输出 mock | BERT 分类器 (本地) | `INTENT_MODEL_URL` |
| 3 | **记忆总结** | 每 N 轮压缩对话摘要（L3 冷记忆） | 大模型（便宜档） | 小模型专用 | `SUMMARY_MODEL` |
| 4 | **反思引擎** | 生成后语义检查（意图一致/幻觉/违规） | 未启用（v1.1 才有） | 可配 BERT 或便宜 LLM | `BERT_API_URL` / `REFLECT_MODEL` |
| 5 | **RAG ReRank** | 检索结果重排序 | 未启用 | `bge-reranker` (本地) | `RERANK_MODEL_URL` |
| 6 | **校验模型** | 输出安全语义校验 | 正则拦截（快而廉价） | 语义级校验小模型 | `VALIDATOR_MODEL_URL` |

### 统一接入方式

所有挂载点共用同一个适配层，避免每个模块各写各的：

```python
# backend/core/models/model_registry.py (v1.1)
class ModelRegistry:
    """
    统一小模型注册表。
    每个挂载点是一个 provider，配置决定走哪个后端。
    """

    def get(self, mount_point: str) -> ModelEndpoint:
        # mount_point: "embedding" | "intent"
        #              | "summary" | "reflect" | "rerank" | "validator"
        config = self._configs[mount_point]
        if config.mock:      # v1.0 阶段：mock 或大模型兜底
            return MockEndpoint(config)
        if config.http_url:  # v1.1+：远程小模型服务（Windows 机器）
            return OpenAICompatEndpoint(config.http_url, config.model)
        return MockEndpoint(config)
```

### 配置切换（Mac mock → Windows 真模型）

```env
# ===== Mac 开发（默认，全部 mock / 大模型兜底）=====
LLM_MOCK=true

# ===== Windows 小模型机器（真模型）=====
# 机器上跑 vLLM / Ollama，暴露 OpenAI 兼容接口
# 例: vLLM 起 bge-m3 → http://192.168.1.100:8001/v1
#      Ollama 起 qwen2.5-7b → http://192.168.1.100:11434/v1

LLM_MOCK=false
EMBEDDING_BASE_URL=http://192.168.1.100:8001/v1
INTENT_MODEL_URL=http://192.168.1.100:8002/v1
REFLECT_MODEL_URL=http://192.168.1.100:11434/v1
RERANK_MODEL_URL=http://192.168.1.100:8003/v1
```

### 切换动作

```
Mac:  git clone + uv sync + LLM_MOCK=true          → 全 mock 跑通
Windows: 起 vLLM/Ollama 容器 → 改 env 指向 IP        → 真模型生效
```

**标志:** 一套代码，两端跑，模型地址全在配置里

---

## 长期方向

| 方向 | 说明 |
|------|------|
| **插件市场** | 第三方 Skill 通过 GitHub 仓库安装 |
| **模型代理** | 统一管理多个 LLM Provider（Deepseek / OpenAI / 本地 vLLM） |
| **联邦审计** | 多租户审计日志统一汇到监管端 |
| **安全攻防** | 红队测试 + 自动加固 prompt 注入规则 |
| **边缘部署** | 轻量版本跑在国产化服务器上（ARM / 信创 OS） |
