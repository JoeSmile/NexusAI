# 00 — 三维面试地图（图 / 面试官 / 求职者）

> 更新：2026-08-05。证据：codebase-memory（~5.5k 节点 / 16k 边）+ 源码锚点。  
> 用途：面试前总览；细节进各深挖篇。

---

## 1) Codebase-memory：项目真长什么样

### 结构事实

| 信号 | 含义 |
|------|------|
| `core` 高 fan-in（~377 in / 24 out） | 中枢在 `backend/core`，不是 `services` 目录名 |
| 边界最密：`routers→core`、`modules→core`、`pipeline→core` | HTTP / 业务模块 / 管线都往 core 汇 |
| 图上的 clusters | 比文件夹更接近「该讲的块」 |

### 八个可讲模块（cluster + hotspot）

1. **认证与租户** — `verify_api_key`（SHA256→`api_keys`→`TenantContext`）；`require_permission`（fan-in 67）；`assert_user_access`
2. **Chat 管线** — `chat_pipeline` → `_run_chat_pipeline` → `build_pipeline` → `ainvoke`；收尾 `log_audit`
3. **护栏** — `check_input`：注入 block + PII redact（在 cache miss 之后）
4. **记忆** — `get_unified_memory_service`：hot/warm/cold
5. **LLM 出口** — `LLMHarness.generate/stream` + `LLMKeyRepository` / key failover
6. **Capability Hub** — `CapabilityRegistry` + `invoke`（model/agent/rag/tool）
7. **RAG** — `RAGService.ask` + 独立 cache（已有 `normalize`）
8. **缓存/Redis** — `CacheManager` / `redis_tools`（静默降级）

### 主调用链（白板用）

```text
X-API-Key → verify_api_key → TenantContext
                ↓
     require_permission("chat:write")
                ↓
        _run_chat_pipeline → graph.ainvoke
                ↓
  auth_check → load_memory → rate_limiter → cache_check
       → guardrails → analyze → build_context → model_router
            ├ short: skill → conversion_hook → END
            └ long:  llm_generate(LLMHarness) → guardrails_out
                     → write_memory → conversion_hook → END
                ↓
           log_audit + LangFuse
```

### 诚实债（加分项）

- Chat exact cache **未归一化**（RAG 已有 `normalize`）→ Task 39 设计动机
- `load_memory` 偏早（hit/block 仍付 I/O）
- Capability **动态权限**，不套死 `@require_permission`——要说清例外
- `services` / `runtime` / `agent` 并存 → 主叙事仍是 **治理网关 + pipeline**

---

## 2) 面试官：会怎么考

### 验三件事

1. 一条请求能否讲通治理链（身份→限流→缓存→护栏→路由→花钱→审计）
2. 能否说清 trade-off（cache 为何在护栏前；短路径为何不调 LLM）
3. 是名词堆砌还是能指到文件级行为

### 高频追问

| 模块 | 典型问 | 答案形状 |
|------|--------|----------|
| Auth | Key 怎么存？跨租户？ | 只存 hash；`is_cross_tenant`；`assert_user_access` |
| Pipeline | 为何 DAG？ | 条件早退；状态在 `PipelineState` |
| Cache | 命中还过护栏吗？ | 假设只缓存干净答案；并说 hash 无归一化 |
| Guardrails | 注入 vs PII？ | block vs redact |
| Model router | 何时不花钱？ | skill + confidence≥0.85 → short |
| Harness | 比直调 API 多啥？ | mock/record/replay、预算、key 链、成本记账 |
| Capability | 和 pipeline？ | Hub=能力调用面；chat=治理主链 |
| 多租户 | 隔离？ | tenant_id 贯穿 cache/memory/key |

### 红灯 / 绿灯

- **红灯**：说不清「钱在哪一步花」；吹完善缓存却说不出 key；把项目讲成通用 Agent 平台
- **绿灯**：主动讲限制 + 演进（Task 39）；对比「治理层 vs 应用层」；能指 LangFuse / `audit_logs`

---

## 3) 求职者：怎么讲、怎么备

### 30 秒定位

> ContextGate 是企业 LLM **治理网关**：进模型前过认证、多租户、限流、缓存、护栏、意图路由；短路径 skill 省成本，长路径走统一 `LLMHarness`；全程审计 + LangFuse。模型可换，合规证据链不断。

### 掌握优先级（ROI）

| 优先级 | 模块 | 深度 | 锚点 |
|--------|------|------|------|
| P0 | Auth + 权限 | Header→TenantContext→权限串 | `verify_api_key`, `require_permission` |
| P0 | Pipeline DAG | 每个条件边为什么在那 | `build_pipeline`, `route_short_or_long` |
| P0 | Harness + 成本 + 短路径 | 见 [07c](07c-harness-cost-shortpath.md) | `model_router`, `LLMHarness` |
| P1 | Guardrails / Memory / Cache | block·三层·key | `check_input`, memory_service, `cache_check` |
| P2 | Intent / RAG / Capability | 侧翼与对照 | intent, `RAGService.ask`, `invoke` |
| P3 | Agent/runtime | 非主叙事除非岗位要 | `runtime`, agent |

### 叙事三件套

1. 架构讲解（DAG + 四角色 RBAC）  
2. Demo（认证→chat/SSE→拦注入→审计/LangFuse）  
3. 一页纸：「集团 AI 中台的治理层建设」

### 别踩的坑

- 别吹「完整 Agent 平台」——图上主价值在 **core 治理 + pipeline**
- 缺陷当加分项讲，别回避
- 国企岗：私有化、审计、不出域、国产模型可接；少吹 star

---

## 三维对照

| 纬度 | 结论 |
|------|------|
| **图** | 中枢 `core`；主故事=治理链+条件早退；Hub/RAG/Agent 是侧翼 |
| **面试官** | 考证据链与 trade-off，不是名词密度 |
| **求职者** | 治理网关定位；P0 练到能白板默画；缺陷可讲演进 |

## 深挖入口

- **A（已写）** → [04a-auth-rbac.md](04a-auth-rbac.md)  
  （Key→TenantContext；四角色；AUTH_00x；scope 防 IDOR；密码只换 key）
- **B（已写）** → [05b-pipeline-nodes.md](05b-pipeline-nodes.md)  
  （13 节点 + 3 条件边；`raw_input`/记忆；Task 39）
- **C（已写）** → [07c-harness-cost-shortpath.md](07c-harness-cost-shortpath.md)  
  （短路径 / Harness / 成本；§7 演进）
- **D（已写）** → [09d-rag-capability.md](09d-rag-capability.md)  
  （Chat / RAG / Hub；动态权限；L1 normalize）

- **可观测（已写）** → [12o-observability.md](12o-observability.md)  
  （LangFuse 怎么读 / Prometheus 指标名 / 审计；采样与 GAP-08）

推荐串讲：**A → B → C**，穿插 **D**，用 **可观测** 收尾「出问题怎么查」。
