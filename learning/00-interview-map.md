# 00 — 三维面试地图（图 / 面试官 / 求职者）

> 更新：2026-08-05。证据：codebase-memory（~5.5k 节点 / 16k 边）+ 源码锚点。  
> 用途：面试前总览；细节进各深挖篇。  
> **主链目标态：人 JWT（Chat ∥ Workflow）/ 机 API Key（仅 Workflow）**（[pilot-b §9](../docs/superpowers/specs/2026-08-05-enterprise-pilot-b-gaps-design.md)）。  
> **实现顺序（计划）：先链 A 后链 B** — 见 [master plan](../docs/superpowers/plans/2026-08-05-pilot-b-master-plan.md)；**代码现状仍是单钥匙，且无无独立 Workflow Runner**。

---

## 1) Codebase-memory：项目真长什么样

### 结构事实

| 信号 | 含义 |
|------|------|
| `core` 高 fan-in（~377 in / 24 out） | 中枢在 `backend/core`，不是 `services` 目录名 |
| 边界最密：`routers→core`、`modules→core`、`pipeline→core` | HTTP / 业务模块 / 管线都往 core 汇 |
| 图上的 clusters | 比文件夹更接近「该讲的块」 |

### 八个可讲模块（cluster + hotspot）

1. **认证与租户** — 现状 Key；目标 JWT∥machine + OrgScope（[03](03-org-security.md)/[04a](04a-auth-rbac.md)）
2. **Chat 管线** — 人侧模糊 DAG（[05b](05b-pipeline-nodes.md)）
3. **Workflow Runner** — 确定动作执行面（🎯 [06](06-workflow-runner.md)）
4. **护栏** — `check_input`：注入 block + PII redact
5. **记忆** — hot/warm/cold
6. **LLM 出口** — `LLMHarness` + key failover（[07c](07c-harness-cost-shortpath.md)）
7. **Capability Hub** — 注册表 + invoke；Runner 节点（[09d](09d-rag-capability.md)）
8. **RAG / 连接器** — pgvector 知识库 ✅；OA/考勤/财务等外挂 DB·API 🎯（出站 + OrgScope）
9. **缓存/Redis** — 静默降级

### 主调用链（白板用）— 目标态两条入口

共用 `TenantContext` + OrgScope + 护栏/审计；**执行面分流，机器不进 Chat 管线。**  
数据面（RAG / 外挂 DB·OA API）挂在 **Capability 节点或 RAG 直问** 上，不另开旁路引擎。

```text
链 A · 人                         链 B · 机
登录 → JWT                        X-API-Key (machine only)
→ verify_session                  → verify_api_key
→ TenantContext + OrgScope        → TenantContext + OrgScope
        │                                   │
        ▼                                   ▼
  人侧入口分流                      【不进 Chat 管线】
   ┌────┴─────┐                             │
   ▼          ▼                             ▼
 Chat 管线   工作台「运行」            Workflow 执行入口
 (模糊)      （确定 · 同右）           （确定 · 直连）
   │          │                             │
   │          └────────────┬────────────────┘
   │                       ▼
   │              Workflow Runner
   │              · IR：自研 / Coze / 后期画布
   │              · 节点 = 已授权 capability
   │              · 二次鉴权(acting_user) + OrgScope
   │              · 可申请 → 挂起等批 → resume
   │                       │
   │         ┌─────────────┼─────────────┐
   │         ▼             ▼             ▼
   │      Hub 节点      RAG 节点      连接器节点
   │    (model/tool/   (知识库)     (外挂数据)
   │     agent…)           │             │
   │         │             ▼             ▼
   │         │        pgvector KB    出站 connector
   │         │        · upload/ask   machine key
   │         │        · L1/L2 cache  · OA / 考勤 / 财务
   │         │        · tenant 隔离  · 外挂 DB / 第三方 API
   │         │                       · 行级跟 acting_user
   │         │                       · 禁浏览器持密钥
   │         └─────────────┬─────────────┘
   │                       │
   ▼                       │
 auth→…→model_router       │
  ├ short: skill           │
  └ long: LLMHarness       │
   │    （也可被 Runner    │
   │     的 model 节点调用）│
   └───────────┬───────────┘
               ▼
      log_audit + LangFuse
   （acting_user · credential_kind · org · run_id · connector_key_id）
```

**数据面一句话：**  
- **RAG** = 墙内知识（制度/文档 → pgvector），Chat 可间接用、Runner 可挂 `kind=rag` 节点，也可 `/api/rag/ask` 直问。  
- **连接器** = 墙内业务数据（OA/考勤/财务、外挂 DB、第三方 API）；只经 Runner/Hub 出站节点 + **服务端 connector key** + OrgScope；不是 Chat 管线私藏旁路。

**入口一句话：** 人可走 Chat（模糊）或点「运行」进 Workflow；**机器只跑 Workflow**；编排来源可换，Runner 与数据闸不变。

#### 现状（代码今天还这样 —— 面试要主动说）

```text
X-API-Key → TenantContext → chat 或 capability invoke 或 /api/rag/ask
  · RAG/pgvector ✅ 已有
  · 外挂 OA/考勤连接器 🎯 骨架/待建（Hub external_app 雏形）
  · 人机未拆；无独立 Workflow Runner；无 OrgScope
密码登录只发 cg_ → 目标 JWT；机器应打 workflow run，不是 /chat
```

### 诚实债（加分项）

- **人机凭证未拆**（§9 / J0.5）— 现状单钥匙；演进 JWT ∥ machine Key
- **无独立 Workflow Runner**（§10 T1）— 机/人「运行」目标态直连 Runner，不进 Chat
- **权限申请 / 数据安全红线**（§10 S1–S4）— 挂起等批绝不能变成提权后门；隔离与防伪造优先于「好用」
- Chat exact cache **未归一化** → Task 39
- `load_memory` 偏早；Capability 动态权限例外要说清

### 可讲风险（从 §10 / §11 抽）

详表：[pilot-b §10–§12](../docs/superpowers/specs/2026-08-05-enterprise-pilot-b-gaps-design.md)

1. **Runner 缺失**（T1）  
2. **入口纪律**（T4）— 机器 / 确定动作不进 Chat 管线  
3. **安全红线 S1–S4 + OrgScope**（组织 B）— 申请防伪造、部门子树隔离、票不绕人  
4. **护栏对齐**（T5）  
5. **测得见**（B8）+ 三壳 UX（§12）

---

## 2) 面试官：会怎么考

### 验三件事

1. 能否画清 **两条入口** 如何汇成同一治理链（身份→限流→缓存→护栏→路由→花钱→审计）
2. 能否说清 trade-off（cache 为何在护栏前；短路径为何不调 LLM；人为何不用长期 API Key）
3. 是名词堆砌还是能指到文件级行为（并诚实区分现状 / 目标）

### 高频追问

| 模块 | 典型问 | 答案形状 |
|------|--------|----------|
| Auth | 人为何不用长期 Key？ | 人→JWT 短会话；机→`cg_`；设计 §9，现状仍单钥匙 |
| Auth | Key 怎么存？跨租户？ | 只存 hash；`is_cross_tenant`；`assert_user_access` |
| Auth | 链内有票就能调 OA？ | 否；二次鉴权看 `acting_user`；可申请须过 **S1–S4**，否则只失败不挂起 |
| Pipeline | 为何 DAG？ | 条件早退；状态在 `PipelineState` |
| Cache | 命中还过护栏吗？ | 假设只缓存干净答案；并说 hash 无归一化 |
| Guardrails | 注入 vs PII？ | block vs redact |
| Model router | 何时不花钱？ | skill + confidence≥0.85 → short |
| Harness | 比直调 API 多啥？ | mock/record/replay、预算、key 链、成本记账 |
| Capability | 和 pipeline？ | Chat=人侧模糊入口；**Workflow Runner=确定动作执行面**（机直连；人按钮也走这）；Hub 节点在 Runner 里 |
| 多租户 | 隔离？ | tenant_id 贯穿 cache/memory/key |

### 红灯 / 绿灯

- **红灯**：说机器也走 Chat；把挂起等批讲成随便申请提权；只画一条 Key 当终局  
- **绿灯**：主动讲 **S1–S4 安全红线** + 人 Chat∥Workflow / 机只跑 Workflow；能指 audit / LangFuse

---

## 3) 求职者：怎么讲、怎么备

### 30 秒定位

> NexusAI / ContextGate 是企业 LLM **治理网关**：人侧 JWT 可走 Chat 或点运行 Workflow；机器 API Key **直连 Workflow 执行**（不进 Chat 管线）。编排可自研 / Coze 导入 / 后期画布，执行同一套 Runner + 二次鉴权（挂起等批）。短路径 skill 省成本；全程审计 + LangFuse。

### 掌握优先级（ROI）

| 优先级 | 模块 | 深度 | 锚点 |
|--------|------|------|------|
| P0 | Auth + 权限（双轨） | JWT ∥ machine Key → `TenantContext`；二次鉴权 | `verify_api_key`（现状）；§9 目标 `verify_session` |
| P0 | Pipeline DAG | 每个条件边为什么在那 | `build_pipeline`, `route_short_or_long` |
| P0 | Harness + 成本 + 短路径 | 见 [07c](07c-harness-cost-shortpath.md) | `model_router`, `LLMHarness` |
| P1 | Guardrails / Memory / Cache | block·三层·key | `check_input`, memory_service, `cache_check` |
| P2 | Intent / RAG / Capability | 侧翼与对照；链内挂起 | intent, `RAGService.ask`, `invoke` |
| P3 | Agent/runtime | 非主叙事除非岗位要 | `runtime`, agent |

### 叙事三件套

1. 架构讲解（**双入口** + DAG + 四角色 RBAC）
2. Demo（登录/鉴权→chat/SSE→拦注入→审计/LangFuse；能提一句 Key 拆分演进更好）
3. 一页纸：「集团 AI 中台的治理层建设」

### 别踩的坑

- 别吹「完整 Agent 平台」——图上主价值在 **core 治理 + pipeline**
- 别把 §9 讲成已上线——**设计已签核，代码未拆**
- 缺陷当加分项讲，别回避
- 国企岗：私有化、审计、不出域、国产模型可接；少吹 star

---

## 三维对照

| 纬度 | 结论 |
|------|------|
| **图** | 中枢 `core`；人 JWT/机 Key；Chat∥Runner；**RAG + 外挂连接器**挂节点；OrgScope/二次鉴权 |
| **面试官** | 考双轨身份与 trade-off，不是名词密度 |
| **求职者** | 治理网关定位；白板默画双入口；债可讲演进（§9 / Task 39） |

## 深挖入口

| 序 | 文档 | 用途 |
|----|------|------|
| 总览 | [01](01-architecture.md) | 五层全景 |
| 目标 | [02](02-runtime-split.md) | 人/机 · Chat∥Workflow |
| 目标 | [03](03-org-security.md) | 组织 B · S1–S4 |
| A | [04a](04a-auth-rbac.md) | 认证现状 + 目标指针 |
| Runner | [06](06-workflow-runner.md) | 确定动作执行面 |
| UX | [08](08-ux-shells.md) | 三壳 |
| B | [05b](05b-pipeline-nodes.md) | Chat DAG 代码 |
| C | [07c](07c-harness-cost-shortpath.md) | 成本 / Harness |
| D | [09d](09d-rag-capability.md) | RAG / Hub |
| 收尾 | [12o](12o-observability.md) | 三本账 |
| 需求 | [pilot-b](../docs/superpowers/specs/2026-08-05-enterprise-pilot-b-gaps-design.md) | §9–§12 签核全文 |

推荐串讲：**00 → 01 → 02 → 03 →（抽安全红线）→ 04a → 06 → 08 → 05b → 07c → 09d → 12o**。
