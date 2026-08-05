# 09d — 深挖 D：RAG 与 Capability Hub

> 面试目标：分清三条调用面（Chat 管线 / RAG 直问 / Capability invoke），说清权限例外与缓存差异，不把 Hub 讲成「第二个 LangGraph」。  
> 锚点：`modules/rag/**` · `core/capability/**` · `routers/capability.py` · `rag_router.py`  
> 对照：管线见 [05b](05b-pipeline-nodes.md)；花钱出口见 [07c](07c-harness-cost-shortpath.md)

---

## 0. 先定边界（最重要）

| 调用面 | 入口 | 干什么 | 是不是治理主链 |
|--------|------|--------|----------------|
| **Chat 管线** | `POST /chat` | 通用对话 DAG（记忆/缓存/护栏/短长路径） | ✅ 主叙事 |
| **RAG 直问** | `POST /api/rag/ask` | 知识库检索 + 生成答案 | 侧翼垂直能力 |
| **Capability Hub** | `GET/POST /api/capabilities…` | 能力市场：注册表 + 统一 invoke | 编排/产品化入口 |

**一句话定位：**  
Chat = 治理网关；RAG = 知识问答产品能力；Capability = 把 model/rag/agent/tool/外部应用收成「可列表、可鉴权、可调用」的目录。  
Hub **可以调用** RAG（`executor=rag` → 同源 `RAGService.ask`），但 **不是** 把整条 Chat DAG 再跑一遍。

```text
                    ┌── POST /chat ──────────► LangGraph pipeline ──► LLMHarness
Client ─ API Key ──┤
                    ├── POST /api/rag/ask ───► RAGService.ask ──► 检索+LLM（自有 cache）
                    └── POST /api/capabilities/{id}/invoke
                              │
                              ▼
                         invoke() 分发
                         ├ kind=model  → LLMHarness.stream
                         ├ kind=tool + executor=rag → RAGService.ask（同源）
                         ├ kind=tool + executor=model → Harness
                         ├ kind=agent → agent 路径
                         └ kind=external_app → 连接器
```

---

## 1) RAG — 面试卡片

### 1.1 入口与鉴权

- 路由：`backend/modules/rag/routers/rag_router.py` → `ask_question`
- 守卫：`Depends(_rag_guard)`（租户上下文；具体 permission 以路由为准，通常需登录 key）
- 核心：`RAGService.ask(question, search_k, tenant_id, user_id, trace_id)`

### 1.2 `ask` 主路径（按代码顺序）

```text
normalize(question)                    ← 已做 NFKC/lower/空白（chat exact 尚未对齐）
  → L1 答案缓存 l1_get(tenant, q)
       hit → 审计 cache_hit=1，cost=0，返回
  → L1 miss：record + RAG 侧 rate_limit(miss)
  → 单飞锁 acquire_lock(l1_key)
       未抢到 → wait_l1 短等别人写入
  → estimate_embedding_cost_if_miss（L2 未命中才计 embedding 成本）
  → retrieve_documents（HyDE / ReRank 由 config 开关）
  → LLM 用 context+question 生成
  → l1_set + 审计（llm_cost + embed_cost）
  → finally release_lock
```

### 1.3 检索增强

`retrieve_documents`（`rag_service.py`）：

| 开关 | 行为 |
|------|------|
| HyDE | LLM 写假设文档，再检索，与原问双路合并 |
| ReRank | LLM 重排，失败则截断降级 |

底层：`KnowledgeBase.search_similar` → pgvector。

### 1.4 缓存两层（相对 Chat 更「完整」）

| 层 | Key 语义 | 内容 |
|----|----------|------|
| L1 | 租户 + **normalize** 后的问题 | 整段答案 + sources |
| L2 | `rag:e:{model}:{norm_hash(text[:8000])}` | embedding 向量（768 pack） |

另有：单飞锁、滑动 TTL、PII 探测（`contains_pii`）、Redis 经 `redis_tools` 静默降级。

**面试对比句：**  
「RAG 答案缓存从第一天就 normalize；Chat 管线 exact 还在裸 hash——所以我会讲 Task 39 是在对齐这两套语义。」

### 1.5 诚实债（RAG）

- 生成侧 LLM 可能走模块内 client，**不一定** 100% 等同管线 `LLMHarness.generate` 全套（failover/预算）——要会说「主路径应继续收口」
- HyDE/ReRank 开着会**多轮**调模型，成本与延迟上升
- 空库时应用空态提示，不造假知识（产品原则）

---

## 2) Capability Hub — 面试卡片

### 2.1 为何权限模型特殊（AGENTS.md 拍板）

普通路由：`@require_permission("xxx")` 固定串。  
Capability：`Depends(verify_api_key)` + **每条** `spec.permission` + `capability_visible_to` / `_check_permission`。

原因：市场里能力权限动态变化，无法用一个装饰器写死。

### 2.2 `CapabilitySpec` 字段（会背）

```text
id, name, kind, provider, spec{}, status, cost_model{},
permission（默认空 → 当 chat:write）, tenant_id（* / 某租户）
```

**Kind：** `model | tool | agent | external_app | workflow | datasource`  
（后两者 invoke 里仍可能 `unsupported_kind`）

**Provider：** contextgate / dify / coze / ai-platform / self-hosted …

### 2.3 Registry 加载顺序

`CapabilityRegistry`（`registry.py`）：

1. `model_registry` → `model:{name}`（兼容旧 ModelSpec）  
2. env `CAPABILITY_REGISTRY_JSON`（同 id 覆盖）  
3. DB `capabilities` 表（再覆盖）  

`get`：不存在 → CAP_001；disabled → CAP_002 类错误。

### 2.4 可见性与 invoke 闸门

`capability_visible_to` / `_check_permission`：

| 情况 | 结果 |
|------|------|
| `tenant_id` 非本租户且非跨租户角色 | **CAP_001 伪装 not found**（防探测） |
| 可见但缺 permission | **AUTH_002** insufficient_permissions |
| 通过 | 继续限流/配额/护栏 |

**面试加分：** 「跨租户私有能力对普通租户返回 not found，而不是 403，避免枚举。」

### 2.5 `invoke()` 流水线

```text
registry.get(cap_id)
  → _check_permission
  → check_cap_rate_limit / check_cap_quota
  → prepare_payload_with_guards（入站）
  → 按 kind 分发异步事件流 {event: token|usage|done, ...}
  → guard_output_text（出站，整段）
  → record_cap_quota_usage
```

| kind / executor | 实现 |
|-----------------|------|
| `model` | `LLMHarness.stream`（事件切成 token） |
| `tool` + model executor | 同上 |
| `tool` + rag executor | `_invoke_rag` → **同源** `RAGService.ask`，再假流式切块 |
| `agent` | agent 调用路径 |
| `external_app` | 连接器；未就绪则 upstream error |

路由层：`POST /{cap_id}/invoke` 可短路径 JSON 或长路径 SSE（事件格式对齐 `/chat/streaming`），并 `log_audit(action=capability.invoke)`。

### 2.6 与 Chat 管线的差异（必考对照表）

| 维度 | Chat pipeline | Capability invoke |
|------|---------------|-------------------|
| 图 | LangGraph 13 节点 | 无 DAG；registry 分发 |
| 记忆 | load/write_memory | 默认不进三层记忆 |
| 短路径 skill | model_router | 靠 kind/executor，不是 greeting skill |
| 权限 | 固定 `chat:write` | 每能力 `spec.permission` |
| 缓存 | pipeline exact/template | model 无 L1；rag 叶子走 RAG L1/L2 |
| 护栏 | 节点 guardrails_* | governance `prepare_payload` + `guard_output_text` |
| 观测 | pipeline span 树 | `capability.invoke` observe + 配额 |

---

## 3) 三者如何「拼」——场景题

**Q：制度知识库问答怎么落地？**  
A：内容进 RAG 知识库；对外可 `POST /api/rag/ask`，或注册 `kind=tool, executor=rag` 的 capability 进市场；治理诉求（全员聊天审计/短路径）仍走 `/chat`。不要说「全走 Capability 就等于管线」。

**Q：Hub 里点一个模型能力和 Chat 有何不同？**  
A：都可能打到 `LLMHarness`，但 Chat 多了记忆、意图路由、管线缓存与 A/B；Hub model 更像「受配额/护栏约束的裸生成」。

**Q：为什么 RAG 要单独限流？**  
A：L1 miss 才打 embedding/LLM，miss 路径单独 `check_rate_limit`；与 Chat 租户桶令牌是不同预算面。

---

## 4) 三维速记

### 图

- Hotspot：`CapabilityRegistry.get` fan-in 高；RAG cluster 含 `ask` / `bump_epoch` / upload  
- 边界：`modules→core`、`routers→core`；Hub 在 `core/capability`，RAG 在 `modules/rag`

### 面试官

1. Hub 为何不用 `@require_permission`？→ 动态 permission + 租户可见性  
2. 私有能力对别的租户返回什么？→ not found，防探测  
3. Capability 调 RAG 是否复制一套检索？→ 否，同源 `RAGService.ask`  
4. Chat 与 RAG 缓存谁更正确？→ RAG 已 normalize；Chat exact 待 39  
5. workflow/datasource？→ 模型预留，invoke 可能尚未实现  

### 求职者 60 秒

> 项目里知识问答是独立 RAG 服务：归一化、L1 答案缓存、L2 向量缓存、可选 HyDE/ReRank，审计 `rag.ask`。  
> Capability Hub 是能力目录：双源注册、按能力鉴权、统一 invoke 事件流；模型走 Harness，RAG 叶子复用同一 ask。  
> Chat 管线仍是治理主链。三者共享租户与钥匙体系，但职责不合并——这是刻意的产品分层。

---

## 5) 还能怎么更好（D 域）

| 优先级 | 点 | 改法方向 |
|--------|----|----------|
| P0 | Chat/RAG normalize 对齐 | Task 39；公共 `normalize_text` |
| P0 | RAG 生成走满 Harness | 预算/failover 与 chat 一致 |
| P1 | Capability 成本一本账 | invoke 配额与 `record_consumption` / 日 spent 同源 |
| P1 | 事件流与取消 | SSE abort 时部分 cost 归因 |
| P2 | workflow/datasource 真实现或藏 UI | 避免市场上点开 501 |
| P2 | Agent 与 Hub 叙事收口 | 孤儿路径别和 invoke 双故事（Task 31 方向） |

---

## 6) 自测

1. 画出三条入口，各标「有无 LangGraph / 有无 L1 normalize」  
2. 默写 `_check_permission` 两种失败码  
3. 说出 `executor=rag` 最终调用的函数名  
4. 各举一个「该用 Chat / 该用 RAG / 该用 Hub」的场景  

```bash
sed -n '236,320p' backend/modules/rag/services/rag_service.py
sed -n '58,84p' backend/core/capability/invoke.py
sed -n '276:320p' backend/core/capability/invoke.py
head -40 backend/routers/capability.py
```

---

## 7) 衔接

- B 管线 → [05b](05b-pipeline-nodes.md)  
- C Harness → [07c](07c-harness-cost-shortpath.md)  
- 下一深挖：**A Auth/RBAC**（三条入口共用的钥匙与角色）
