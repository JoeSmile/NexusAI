# ContextGate: Emotional Chat → 企业级通用 LLM 管线 改造计划

> **状态:** Plan 阶段，不执行代码
> **项目名称:** ContextGate
> **标语:** The Intelligent Gateway for LLM Context Management
> **目标:** 将 emotional_chat demo 改造为可观测、可审计、可扩展、安全的企业级 LLM 前置处理管线
> **执行方式:** 交给 Cursor 按 Subtask 逐个实现。每个 Subtask 应 5-10 分钟内完成，完成后 git commit
> **包管理:** 统一用 `uv` 管理 Python 依赖

---

## 一、架构总览

### 当前架构（emotional_chat v3.0）

```
用户 → FastAPI → 面条式顺序调用 → MySQL/SQLite + ChromaDB → Print日志
```

### 目标架构

```
用户 → FastAPI → LangGraph StateGraph → pgvector → LangFuse
                                                  ↑
                          Auth(RBAC0+App权限) → Guardrails → Prometheus + Grafana
```

### 管线图 (LangGraph)

```text
[START]
  │
  ▼
① auth_check           ← API Key 校验 + RBAC0 权限 + 应用级权限 ← ★安全
  │
  ▼
② load_memory          ← 加载 L1 热记忆 + L2 温记忆 (pgvector)
  │
  ▼
③ rate_limiter         ← 桶令牌限流 + 成本预算检查 ← ★安全
  │
  ▼
④ cache_check          ← 精确缓存 + 意图指纹缓存
  │
  ├── [hit] ──► [END] (直接返回缓存结果)
  │
  └── [miss] ──► continue
                    │
                    ▼
           ⑤ guardrails_input     ← PII脱敏 + prompt注入检测 ← ★安全
                    │
                    ▼
           ⑥ analyze_parallel     ← 情绪分析 + 意图识别 (并行)
                    │
                    ▼
           ⑦ build_context        ← 上下文组装 (记忆+画像+历史)
                    │
                    ▼
           ⑧ model_router         ← 短路径(Intent→Skill) / 长路径(LLM)
                    │
                    ├── [short path] execute skill → [END]
                    │
                    └── [long path] llm_generate → guardrails_output
                                                    │
                                                    ▼
                                           ⑨ write_memory + audit
                                                    │
                                                    ▼
                                                   [END]
```

**每个节点都有 LangFuse span，整张图自动 trace。**

---

## 二、企业级缺口分析

### 现有安全漏洞清单（按严重程度）

| P级 | 漏洞 | 代码位置 | 影响 |
|-----|------|---------|------|
| **P0** | **零认证** | 所有 router 无 Depends, user_id 自传串 | 任何人都能调任何接口 |
| **P0** | **Prompt 注入无防** | chat_service.py:169 → 用户输入直接进 LLM | 一句话让 LLM 叛变 |
| **P0** | **文件上传裸奔** | app.py 挂 StaticFiles, 不校验 MIME | 上传 .html/shell 可 XSS/RCE |
| **P0** | **异常抛内部信息** | 500 error 直接把 str(e) 返回前端 | 暴露路径、配置、密码 |
| **P0** | **默认密码硬编码** | docker-compose.yml MYSQL_PASSWORD | 生产不换密码直接沦陷 |
| **P1** | **无 PII 脱敏** | 手机号/身份证直接进 LLM | 违反个保法，数据出域 |
| **P1** | **CORS 配置遗留** | app.py 注释里写了 allow_origins=["*"] | 跨站风险 |
| **P1** | **请求体大小不限** | 没 max_body_size | 大 payload 打爆内存 |
| **P2** | **LLM 输出无 XSS 转义** | 前端 react-markdown 直接渲染 | LLM 被注后返回恶意脚本 |
| **P2** | **SQL 注入面** | SQLAlchemy ORM 安全，但 raw SQL 路径未审计 | 理论上可被利用 |

### 缺失的企业级能力

| # | 能力 | 现状 | 对应 Subtask |
|---|------|------|-------------|
| 1 | **认证 + RBAC0 + 应用级权限** | 零认证 | 2.1-2.5 |
| 2 | **跨租户审计 (super_admin / auditor)** | 无 | 2.4, 3.1-3.4 |
| 3 | **审批流程 (user:approve)** | 无 | 2.5 |
| 4 | **Prompt 注入防御** | 无 | 9.2 |
| 5 | **PII 脱敏入站** | 无 | 9.2 |
| 6 | **输出安全审查** | 评估引擎只打分不拦截 | 9.3 |
| 7 | **文件上传加固** | 生产级漏洞 | 10.1 |
| 8 | **多租户数据隔离** | user_id 就是字符串 | 2.4, 3.4 |
| 9 | **审计溯源** | 只有 system_logs 表 | 3.2-3.3 |
| 10 | **速率限制** | 无限流 | 7.2 |
| 11 | **成本治理 + 模型路由** | 所有请求一个模型 | 7.1, 7.6 |
| 12 | **断路器和降级** | LLM 挂了直接抛 500 | 11.1 |
| 13 | **SLA 指标** | 无 p50/p95 | 12.2-12.3 |
| 14 | **CI/CD** | 无 | 15.1-15.3 |
| 15 | **生产部署** | 仅 dev docker-compose | 14.2, 16.1-16.2 |
| 16 | **社区治理** | 无 | 17.1-17.5 |
| 17 | **合规资产** | 无 | 17.4 |

---

## 三、存储层设计

### pgvector 表结构

见 `backend/database/init_pgvector.sql`（已创建）。SQLAlchemy 模型层使用 `pgvector.sqlalchemy.Vector` 类型。

| 表 | 替代对象 | 关键特性 |
|---|---|---|
| `chat_sessions` | 原 MySQL `chat_session` | +tenant_id 列 |
| `chat_messages` | 原 MySQL `chat_message` + ChromaDB | +embedding(Vector(1536)) |
| `user_memories` | 原 `MemoryItem` + 用户画像 | L2 温记忆, key-value |
| `cold_memories` | ChromaDB 记忆检索 | L3 冷记忆, 摘要向量 |
| `audit_logs` | **新增** | 谁/何时/什么操作/输入/输出/trace_id |
| `api_keys` | **新增** | 租户级 API Key, 含 role |
| `roles` | **新增** | RBAC0 角色定义 |
| `user_app_perms` | **新增** | 用户在应用级的额外权限 (resource:action) |
| `approval_requests` | **新增** | 权限审批请求表 |
| `cache_entries` | **新增** | 缓存键值对（精确+指纹） |

---

## 四、权限模型（核心设计）

### 4.1 权限层次

```
super_admin (跨租户)
  ├── auditor (跨租户, 只读审计日志)
  │
  └── 租户: acme
      ├── tenant_admin (本租户管理 + 审批权限)
      │
      └── 用户: u001
          ├── 角色: user
          └── 应用权限: chat:write, kb:query
```

### 4.2 四种角色

| 角色 | 跨租户? | 能做什么 | 不能做什么 |
|------|---------|---------|-----------|
| **super_admin** | ✅ | 跨租户审计、查所有日志、管所有租户配置、管理 auditor | 不能发消息、不能改业务数据 |
| **auditor** | ✅ | 只看审计日志 + trace + cost 报表 + 导出报告 | 不能发消息、不能改配置、不能管理用户 |
| **tenant_admin** | ❌ | 管本租户的 API Key/用户/权限审批、配置模型路由/成本预算 | 不能看其他租户 |
| **user** | ❌ | 只能聊天/查知识库等业务操作，看自己的对话历史 | 不能管理、不能看别人对话 |

### 4.3 RBAC0 + 应用级权限

**Permission = `{resource}:{action}`**

| Permission | 含义 | 分配对象 |
|---|---|---|
| `chat:read` | 查看对话历史 | user, tenant_admin |
| `chat:write` | 发送消息 | user, tenant_admin |
| `admin:api_keys` | 管理 API Key | tenant_admin |
| `admin:approve` | 审批权限申请 | tenant_admin |
| `admin:config` | 修改租户配置(模型/路由/预算) | tenant_admin, super_admin |
| `audit:read` | 查看审计日志 | auditor, super_admin |
| `audit:export` | 导出审计报告 | auditor, super_admin |
| `admin:*` | 所有权限 | super_admin |

### 4.4 审批流程

```
用户 u001 想用知识库:
  POST /api/permissions/request
  { user_id: "u001", resource: "kb", action: "query" }
  
  → approval_requests 表新增一条, status="pending"

tenant_admin 看到:
  GET /api/admin/pending-requests → 看到 u001 的申请

tenant_admin 审批:
  POST /api/admin/approve
  { request_id: 5, action: "approve" }
  
  → user_app_perms 表新增: u001, "kb", "query"
  → approval_requests.status = "approved"

用户下次请求:
  @require_permission("kb:query") → pass ✅
```

### 4.5 数据隔离原则

```python
# 所有查询自动加 tenant_id 过滤
# ChatMessage 查询额外加 user_id（用户不能偷窥别人对话）
# audit_logs 只有 cross_tenant=True 的角色能查
```

---

## 五、Mock 策略

| 组件 | Mock 方式 | 原因 |
|------|----------|------|
| **主 LLM** | **不 Mock**，走真实 API key | 需要真实 token 消耗和 trace |
| **Embedding** | `np.random.randn(1536)` | 只验证 pgvector 检索链路 |
| **情绪分析** | 改为直接调大模型 JSON 输出 | 省本地模型空间 |
| **意图识别** | 同上，大模型链式调用 | 省本地模型空间 |
| **记忆提取** | 预设 5 组剧本 (Subtask 13.3) | 验证 L2/L3 读写链路 |

### Mock 开关

```env
LLM_MOCK=true
LLM_MOCK_DATA_DIR=./data/mock_data
```

---

## 六、Subtask 清单

---

### Task 0: Rebranding — ContextGate

> 全面改名为 **ContextGate**。项目名 `emotional-chat` → `context-gate`。
> 作者改为 `Joe`。

**Subtask 0.1: 项目元数据**
- 修改: `pyproject.toml:1,3,8-9,11,106`
- name: `emotional-chat` → `context-gate`
- description: → `The Intelligent Gateway for LLM Context Management`
- authors: → `Joe`
- keywords: +`llm-gateway`, `context-management`, `observability`

**Subtask 0.2: 后端代码脱敏**
- 修改: `backend/app.py:95,96,209` — FastAPI title/description/root name
- 修改: `backend/routers/chat.py:27`, `memory.py`, `emotion_analysis.py`, `feedback.py`, `agent.py` — 路由 tag 改为英文
- 修改: `backend/modules/llm/core/llm_core.py` — `SimpleEmotionalChatEngine` → `ChatEngine`
- 修改: `backend/modules/llm/core/llm_with_plugins.py` — `EmotionalChatEngineWithPlugins` → `ChatEngineWithTools`
- 修改: `backend/xinyu_prompt.py` — 去掉所有"心语"字眼
- 修改: `config.py:13` — 去情感化

**Subtask 0.3: README 重写**
- 修改: `README.md`, `README.en.md`
- 新内容: 通用 LLM 管线网关定位，不再提情感陪伴

**Subtask 0.4: Docker 配置改名**
- 修改: `docker-compose.yml`, `docker-compose.local.yml` — service name `backend` → `contextgate`
- 修改: `monitoring/prometheus.yml` — job_name `emotional-chat-backend` → `contextgate`

**Subtask 0.5: 前端保留（开发期测试客户端）**
- 不动 `frontend/` 任何文件
- 视为开发期测试客户端，部署、CI 均不依赖前端
- README 保留 `http://localhost:3000` 说明（注：v1.0 正式版替换为 Playground）

**验证:**
```bash
grep -r "心语\|情感陪伴" backend/ --include="*.py"  # → 0
grep "name.*=.*emotional-chat" pyproject.toml         # → 0
```

---

### Task 1: pgvector 迁移

**Subtask 1.1: pyproject.toml 依赖更新**
- 移除: `PyMySQL`, `chromadb`, `langchain-chroma`, `sentence-transformers`, `transformers`
- 添加: `psycopg2-binary>=2.9.0`, `sqlalchemy-pgvector>=0.7.0`, `pgvector>=0.3.0`
- 运行: `uv lock && uv sync`

**Subtask 1.2: SQLAlchemy pgvector 模型定义**
- 创建: `backend/database/pgvector_session.py`
- 定义: `Base`, `ChatMessage`, `ChatSession`, `UserMemory`, `ColdMemory`, `AuditLog`, `ApiKey`, `Role`, `UserAppPerm`, `ApprovalRequest`, `CacheEntry`
- embedding 列用 `Vector(1536)` 不是 `ARRAY(Float)`

**Subtask 1.3: PGVectorSession 类**
- 创建: `backend/database/pgvector_session.py` 中的 `PGVectorSession`
- 方法: `__init__(db_url)`, `search_similar(tenant_id, embedding, limit)`, `get_session()`
- `search_similar` 用 `cosine_distance` 算子

**Subtask 1.4: vector_ops.py — 向量 CRUD**
- 创建: `backend/database/vector_ops.py`
- 函数: `store_embedding(message_id, embedding)`, `search_memories(tenant_id, query_vec, limit)`, `delete_expired_entries(ttl_hours)`

**Subtask 1.5: database.py 兼容适配**
- 修改: `backend/database.py` — 在 `_resolve_database_url()` 加 `DB_TYPE=postgresql` 分支
- 老 `DatabaseManager` 标记 `# DEPRECATED`
- 新增快捷函数 `get_pg_session()`

**验证:**
```bash
uv run python -c "from pgvector.sqlalchemy import Vector; print('✅ pgvector ok')"
uv run python -c "from backend.database.pgvector_session import PGVectorSession; print('✅ session ok')"
```

---

### Task 2: 认证 + RBAC0 + 应用级权限 + 审批

**Subtask 2.1: TenantContext 和权限数据模型**
- 创建: `backend/core/auth/models.py`
- `TenantContext` dataclass（tenant_id, user_id, role, extra_permissions, is_cross_tenant）
- `has_permission()` 方法（支持通配符 `admin:*`）
- `Permission` 枚举或常量

**Subtask 2.2: verify_api_key Depends**
- 创建: `backend/core/auth/api_key_auth.py`
- 函数: `verify_api_key(api_key: str = Security(APIKeyHeader(...))) -> TenantContext`
- SHA256 哈希 API Key，查 `api_keys` 表
- 失败返回 `401 {"code": "AUTH_001"}`

**Subtask 2.3: require_permission + cross_tenant_only 装饰器**
- 创建: `backend/core/auth/permissions.py`
- `require_permission(perm)` → 返回 FastAPI Depends 函数（不是普通装饰器）
- `cross_tenant_only()` → 只允许 super_admin/auditor
- `require_role(role_name)` → 按角色名过滤

**Subtask 2.4: 权限数据库表定义**
- 修改: `backend/database/init_pgvector.sql` — +`api_keys`, `roles`, `user_app_perms`, `approval_requests` 表
- 创建: `backend/database/pgvector_session.py` 中对应模型

**Subtask 2.5: admin.py — 管理 API**
- 创建: `backend/routers/admin.py`
- API: 创建/吊销 API Key, 查看待审批列表, 审批通过/拒绝
- 路由: `POST /api/admin/api-keys`, `DELETE /api/admin/api-keys/{id}`, `GET /api/admin/pending-requests`, `POST /api/admin/approve`
- 修改: `backend/app.py` — 注册 admin 路由

**验证:**
```bash
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{}'
# → 401
```

---

### Task 3: 多租户隔离 + 审计日志

**Subtask 3.1: 租户中间件**
- 创建: `backend/core/tenant.py`
- FastAPI middleware 在请求开始时注入 `request.state.trace_id`
- 从 `TenantContext` 提取 tenant_id

**Subtask 3.2: 审计日志写入（fire-and-forget）**
- 创建: `backend/core/audit.py`
- 函数: `log_audit(background_tasks, tenant_id, user_id, action, trace_id, input, output, model, tokens, cost, latency_ms, error_code, ip, ua)`
- 使用 FastAPI `BackgroundTasks`，不 block 主请求
- 审计日志存原始输入（脱敏前），不是脱敏后

**Subtask 3.3: 审计导出 API**
- 创建: `backend/core/audit_export.py`
- 创建: `backend/routers/audit.py` — `GET /audit/logs`, `GET /audit/export`
- 只有 `cross_tenant_only` 角色能访问

**Subtask 3.4: ORM 数据隔离**
- 在 `PGVectorSession` 中封装 `query_with_tenant()` 方法
- 所有 `ChatMessage` 查询自动加 `WHERE tenant_id=:tid AND user_id=:uid`

**验证:**
- 租户 A 查不到租户 B 的数据
- auditor 跨租户看审计日志，但看不到对话内容

---

### Task 4: LangGraph 管线重构（最大 Task）

**Subtask 4.1: PipelineState 定义**
- 创建: `backend/pipeline/state.py`
- 类型: `TypedDict`，不是 Pydantic
- 每个字段精确类型: `list[dict]`, `dict[str, str]`, `Optional[str]`

**Subtask 4.2: 节点 — auth_check**
- 创建: `backend/pipeline/nodes/auth_check.py`
- 调用 Task 2 的 `verify_api_key`，将 tenant 注入 state

**Subtask 4.3: 节点 — load_memory + rate_limiter**
- 创建: `backend/pipeline/nodes/load_memory.py` — 查 pgvector 加载 L1+L2 记忆
- 创建: `backend/pipeline/nodes/rate_limiter.py` — 桶令牌检查

**Subtask 4.4: 节点 — cache_check + guardrails_input**
- 创建: `backend/pipeline/nodes/cache_check.py`
- 创建: `backend/pipeline/nodes/guardrails_input.py`（具体逻辑在 Task 9）

**Subtask 4.5: 节点 — analyze_parallel（并行执行）**
- 创建: `backend/pipeline/nodes/analyze_parallel.py`
- 用 `asyncio.gather` 并行跑情绪分析 + 意图识别
- 不是 `ThreadPoolExecutor`

**Subtask 4.6: 节点 — build_context + model_router**
- 创建: `backend/pipeline/nodes/build_context.py`
- 创建: `backend/pipeline/nodes/model_router.py`（双路径路由逻辑在 Task 7）

**Subtask 4.7: 节点 — llm_generate + guardrails_output + write_memory**
- 创建: `backend/pipeline/nodes/llm_generate.py`
- 创建: `backend/pipeline/nodes/guardrails_output.py`
- 创建: `backend/pipeline/nodes/write_memory.py`

**Subtask 4.8: 图组装 + 条件边**
- 创建: `backend/pipeline/graph.py`
- `StateGraph(PipelineState)` 组装所有节点
- 条件边: `cache_check` 命中 → `END`，未命中 → continue
- 条件边: `model_router` 短路径 → `END`，长路径 → `llm_generate`

**Subtask 4.9: FastAPI 转接层**
- 创建: `backend/pipeline/router.py`
- `POST /chat` 路由: 构造 `PipelineState` → `app.ainvoke()` → 转回 `ChatResponse`
- `@observe(name="chat.pipeline")` （Task 5 的 LangFuse）

**Subtask 4.10: 老代码退役**
- 老的 `chat_service.py` 不再被新路由引用
- 保留文件不动，加文件头注释 `# DEPRECATED: 请使用 backend/pipeline/router.py`

**验证:**
```bash
uv run python -c "
from backend.pipeline.graph import compiled_graph
print(f'✅ 图编译成功，{len(compiled_graph.nodes)} 个节点')
"
```

---

### Task 5: LangFuse 可观测性

**Subtask 5.1: LangFuse 客户端初始化**
- 创建: `backend/observability/langfuse_client.py`
- 单例模式，从环境变量读 `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
- 修改: `pyproject.toml` — +`langfuse`

**Subtask 5.2: 管线节点 LangFuse 埋点**
- 在每个节点的函数上加 `@observe()`（异步用 `as_type="generation"`）
- `llm_generate` 节点更新 `langfuse_context.update_current_generation()` 传 token/cost

**Subtask 5.3: FastAPI 路由 LangFuse 集成**
- 在 `pipeline/router.py` 的 `chat_pipeline` 函数上加 `@observe()`
- trace name: `chat_{tenant_id}/{session_id}`

**验证:** 发消息 → `http://localhost:3001` 看到完整 trace

---

### Task 6: 缓存系统

**Subtask 6.1: 精确缓存（exact match）**
- 创建: `backend/pipeline/cache/exact_cache.py`
- key: `exact:{tenant_id}:{user_id}:{query_hash}` — TTL=5min
- hash 用 `hashlib.sha256(message.encode()).hexdigest()[:16]`

**Subtask 6.2: 意图指纹缓存**
- 创建: `backend/pipeline/cache/fingerprint_cache.py`
- key: `template:{fingerprint}` — TTL=24h
- 存 pgvector `cache_entries` 表

**Subtask 6.3: 意图指纹生成**
- 创建: `backend/pipeline/cache/intent_fingerprint.py`
- `make_fingerprint(intent, entities)` → `"{intent}:{sha256(entities)[:12]}"`
- `_normalize_entity(key, value)` 标准化实体值

**验证:** 同一 query 发两次 → 第二次 < 10ms

---

### Task 7: 成本治理 + 模型路由 + Skill 双路径

**Subtask 7.1: CostManager**
- 创建: `backend/core/cost_manager.py`
- `check_budget(tenant_id, estimated_cost) -> bool`
- `record_consumption(tenant_id, cost, tokens)`
- 预算从 `tenant_config` 表读取

**Subtask 7.2: RateLimiter（桶令牌）**
- 创建: `backend/core/rate_limiter.py`
- 桶令牌算法: 每秒 10 请求/租户，突发 20
- 超出返回 `429 RateLimitExceeded`

**Subtask 7.3: BaseSkill + SkillResult**
- 创建: `backend/skills/base.py`
- `BaseSkill(ABC)`: `id`, `name`, `description`, `trigger_intents`, `tool_schema`, `execute()`
- `SkillResult`: `output`, `latency_ms`, `success`, `error`

**Subtask 7.4: SkillRegistry + 自动发现**
- 创建: `backend/skills/registry.py`
- `discover()`: 用 `pkgutil.iter_modules` 扫描 `backend/skills/builtin/`
- `register(skill)`: 注册到 `_intent_map` 和 `_llm_tools`
- `get_skill_for_intent(intent, confidence, threshold=0.85)`

**Subtask 7.5: 内置 Skill — emotion_response**
- 创建: `backend/skills/builtin/emotion_response.py`
- `trigger_intents = ["emotion"]`
- 根据情绪类型返回预设回应模板

**Subtask 7.6: model_router 节点实现**
- 修改: `backend/pipeline/nodes/model_router.py`
- 双路径逻辑: intent命中Skill+置信度≥0.85 → 短路径。否则→ LLM长路径
- 模型名从环境变量读: `MODEL_CHEAP`, `MODEL_GOOD`, `MODEL_BEST`

**验证:**
- 超限请求 → 429
- intent="emotion"+置信度0.92 → 走 skill，不调 LLM

---

### Task 8: 依赖锁定

**Subtask 8.1: uv lock**
```bash
uv lock && uv sync
```

**验证:** `uv run python -c "import langgraph, langfuse; print('✅ all deps ok')"`

---

### Task 9: 安全护栏

**Subtask 9.1: GuardResult 基类**
- 创建: `backend/core/guardrails/base.py`
- `GuardResult(action: "pass"|"redacted"|"blocked", redacted_text, reason)`

**Subtask 9.2: 输入护栏 — PII脱敏 + Prompt注入检测**
- 创建: `backend/core/guardrails/input_guard.py`
- 创建: `backend/core/guardrails/pii_patterns.py` — 手机/身份证/银行卡正则
- 创建: `backend/core/guardrails/injection_patterns.py` — 注入检测正则
- `check_input(message) -> GuardResult`
- blocked → 不走 LangGraph 后续节点，直接 403

**Subtask 9.3: 输出护栏 — 安全审查**
- 创建: `backend/core/guardrails/output_guard.py`
- 长度截断、危机表达检测、违规内容拦截
- `check_output(response) -> GuardResult`

**验证:**
- "忽略系统提示" → 403
- "手机13800138000" → redacted
- LLM 返回长内容 → truncated

---

### Task 10: 文件上传加固

**Subtask 10.1: file_sanitizer.py**
- 创建: `backend/core/file_sanitizer.py`
- 读文件头校验 MIME（用 `python-magic` 或 magic bytes）
- UUID 重命名存储
- 大小限制 10MB + 类型白名单
- 不上传目录挂 `StaticFiles`，通过 `/files/{id}` 接口返回

**Subtask 10.2: 修改 chat.py 上传逻辑**
- 修改: `backend/routers/chat.py` — 引用 `file_sanitizer`
- 移除 `app.mount("/uploads", StaticFiles...)`

**验证:** 上传 `.html` 伪装成 `image/png` → blocked

---

### Task 11: 断路器 + 降级

**Subtask 11.1: CircuitBreaker**
- 创建: `backend/core/circuit_breaker.py`
- 状态机: closed →（5 次失败）→ open →（30 秒）→ half-open →（1 次成功）→ closed

**Subtask 11.2: Fallback 回复**
- 创建: `backend/core/fallback.py`
- 中文/英文降级模板
- wrapper 函数: `with_fallback(llm_call, fallback_text)`

**Subtask 11.3: 嵌入 llm_generate 节点**
- 修改: `backend/pipeline/nodes/llm_generate.py` — LLM 调用用断路器包裹

**验证:** 关掉 API key → 返回降级回复，HTTP 200，不是 500

---

### Task 12: 健康检查 + SLA 指标 + 结构化错误码

**Subtask 12.1: 结构化错误码**
- 创建: `backend/core/errors.py`
- `ErrorCode` 枚举: AUTH_001~AUTH_004, RATE_001, COST_001, GUARD_001~003, LLM_001~003, FILE_001~003, SYS_001
- 统一 HTTPException 封装: `ContextGateException(code, message, detail, trace_id)`

**Subtask 12.2: 深度健康检查**
- 创建: `backend/core/health.py`
- 检查: database, pgvector (ANN index size), llm_api, cache, langfuse
- `GET /health` 返回所有子服务状态

**Subtask 12.3: Prometheus 指标**
- 创建: `backend/core/metrics.py`
- 指标: request_duration_ms(p50/p95/p99), requests_total, tokens_total, cache_hit_ratio, guardrails_blocked_total, cost_total, errors_total
- 所有指标带 `tenant` label
- FastAPI 挂 `/metrics` 端点

**验证:**
```bash
curl http://localhost:8000/health   # → 所有 checks up
curl http://localhost:8000/metrics   # → Prometheus 格式
curl http://localhost:8000/chat -H "X-Bad-Key: x"  # → {"error":{"code":"AUTH_001"}}
```

---

### Task 13: Seed 数据 + Mock 剧本

**Subtask 13.1: seed_api_keys.py**
- 创建: `scripts/seed_api_keys.py`
- 创建 2 个租户（acme, beta）各一个 user key
- 创建 1 个 super_admin key, 1 个 auditor key
- 创建 1 个 tenant_admin key
- Key 格式: `cg_{secrets.token_hex(16)}`
- 打印出所有 key（用户需要存）

**Subtask 13.2: seed_pgvector.py**
- 创建: `scripts/seed_pgvector.py`
- 写入 2 个租户的示例对话数据
- 写入 2 个场景的记忆数据
- Embedding 用 `np.random.seed(42); np.random.randn(1536).tolist()`

**Subtask 13.3: Mock 场景 YAML**
- 创建: `data/mock_data/scenarios/working_anxiety.yaml`
- 创建: `data/mock_data/scenarios/heartbreak.yaml`
- 创建: `data/mock_data/scenarios/happy.yaml`
- 创建: `data/mock_data/scenarios/advice.yaml`
- 创建: `data/mock_data/scenarios/injection_attack.yaml`

**验证:**
```bash
uv run python scripts/seed_api_keys.py   # → 输出 key
uv run python scripts/seed_pgvector.py   # → 表有数据
```

---

### Task 14: Docker + uv 最终化

**Subtask 14.1: Dockerfile 重写（uv multi-stage）**
- 修改: `Dockerfile`
- Builder stage: `COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/` + `uv sync --frozen --no-dev`
- Runtime stage: 从 builder 复制 `.venv`，非 root 用户运行

**Subtask 14.2: docker-compose.local.yml 最终化**
- 修改: `docker-compose.local.yml`
- service: `contextgate` (从 builder 构建, 本地代码挂载, uvicorn)
- service: `postgres` (pgvector/pgvector:pg16, 健康检查)
- service: `langfuse` (ghcr.io/langfuse/langfuse:latest, 环境变量)
- networks + volumes

**Subtask 14.3: Makefile 更新（uv）**
- 修改: `Makefile`
- `install` → `uv sync`
- `run` → `uv run uvicorn backend.app:app`
- 删除 pip 相关命令

**Subtask 14.4: config.env 创建**
- 创建: `config.env`
- DATABASE_URL=postgresql://...
- LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY
- LLM_API_KEY/BASE_URL/MODEL
- LLM_MOCK=true

**验证:**
```bash
docker compose -f docker-compose.local.yml up -d
docker compose ps  # → 全部 healthy
```

---

### Task 15: CI/CD — GitHub Actions

**Subtask 15.1: lint + typecheck CI**
- 创建: `.github/workflows/ci.yml`
- trigger: push, pull_request on main
- steps: checkout → uv sync → `uv run ruff check .` → `uv run mypy backend/`

**Subtask 15.2: 单元测试 CI**
- 在 `ci.yml` 中追加 steps
- `uv run pytest tests/ -v --cov=backend`

**Subtask 15.3: Docker 构建 CI**
- 创建: `.github/workflows/docker.yml`
- trigger: tag push `v*`
- buildx multi-platform, push to `ghcr.io/joe/contextgate:latest`

**验证:** PR 提交后 CI 自动跑

---

### Task 16: 生产部署配置

**Subtask 16.1: docker-compose.prod.yml**
- 创建: `docker-compose.prod.yml`
- contextgate: 不加 volumes 挂载代码（构建时就打包）
- postgres: 数据卷持久化
- langfuse: NEXTAUTH_SECRET/SALT 改为环境变量注入
- nginx: 反向代理 + HTTPS（SSL 证书挂载）
- 健康检查 + restart: always

**Subtask 16.2: nginx.conf**
- 创建: `deploy/nginx.conf`
- 代理 `/` → contextgate:8000
- 代理 `/langfuse/` → langfuse:3000
- 限制请求体 20MB
- 速率限制 100 req/s per IP
- CORS 头

**验证:**
```bash
docker compose -f docker-compose.prod.yml config  # → 语法正确
```

---

### Task 17: 项目占领 / Project Ownership

> 从"代码能跑"到"项目属于你"的最后一步。完成后 ContextGate 就是一个完整的开源项目，不是改造过的 demo。

**Subtask 17.1: 法律护城河**
- 创建: `LICENSE` — Apache 2.0（复制标准模板，年份填 2026，作者 Joe）
- 修改: `.gitignore` — 加 `chroma_db/`, `uploads/`, `data/`, `*.env`, `.venv/`, `.test_*`
- 创建: `NOTICE` — 如果引用了原 emotional_chat 的代码，注明 MIT 版权归属
- 所有 py 文件头部加 license header（可选，Apache 2.0 不要求但推荐）

**Subtask 17.2: README 门面级重写**
- 修改: `README.md`
- 结构:
  ```markdown
  # ContextGate
  
  [![License](https://img.shields.io/badge/License-Apache%202.0-blue)]()
  [![Python](https://img.shields.io/badge/python-3.11-blue)]()
  [![CI](https://img.shields.io/github/actions/workflow/status/joe/contextgate/ci.svg)]()
  
  > **The Intelligent Gateway for LLM Context Management**
  
  ## Architecture
  
  [管线图]
  
  ## Quick Start (3 steps)
  
  ## Features
  
  | Category | Feature | Description |
  |---|---|---|
  | Security | Auth + RBAC | API Key + 4 种角色 |
  | Security | Guardrails | Prompt 注入检测 + PII 脱敏 |
  | Observability | LangFuse Tracing | 全链路 trace |
  | Multi-tenant | Data Isolation | 行级隔离 |
  | Caching | Intent Fingerprint | 意图指纹缓存 |
  | Cost | Model Routing | 分级路由 + 预算控制 |
  
  ## Comparison
  
  | Feature | ContextGate | Dify | FastGPT |
  |---|---|---|---|
  | Prompt Injection Defense | ✅ | ❌ | ❌ |
  | PII Redaction | ✅ | ❌ | ❌ |
  | Cross-tenant Audit | ✅ | ❌ | ❌ |
  | Intent Fingerprint Cache | ✅ | ❌ | ❌ |
  | Full-link Tracing | ✅ LangFuse | basic | ❌ |
  | Circuit Breaker | ✅ | ❌ | ❌ |
  
  ## License
  
  Apache 2.0
  ```

**Subtask 17.3: 社区文件**
- 创建: `CONTRIBUTING.md`
  - PR 流程（fork → branch → commit → PR）
  - Commit 规范: Conventional Commits
  - 代码风格: Ruff + mypy
  - DCO: 每个 commit 加 `Signed-off-by: Joe`
- 创建: `SECURITY.md`
  - 漏洞报告邮箱
  - PGP 密钥（可选）
  - 预期响应时间 48h
- 创建: `CODE_OF_CONDUCT.md`
  - 直接 copy [Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/)
- 创建: `CHANGELOG.md`
  - 格式: Keep a Changelog
  - v1.0.0（初始发布）
- 创建: `ROADMAP.md`
  - v1.0: 当前 Plan 全部完成
  - v1.1: RAG 深化（HyDE + ReRank + 多路召回）
  - v1.2: Web UI（管理后台）
  - v2.0: ai-platform 集成

**Subtask 17.4: 合规文档（国企场景杀手锏）**
- 创建: `docs/COMPLIANCE.md`
  - 个保法合规：PII 脱敏在哪层做的、审计日志存多久（默认 180 天）、数据怎么隔离的
  - 数据流向图：用户输入 → guardrails (PII脱敏) → LLM → guardrails (输出审查) → 用户
  - 审计日志 schema + 示例
- 创建: `docs/SECURITY_AUDIT.md`
  - 安全深度防御 7 层模型
  - 每层具体实现 + 代码路径
  - 渗透测试 checklist
- 创建: `docs/DEPLOYMENT.md`
  - 生产部署 checklist（改密码→ HTTPS → 环境变量 → 监控）
  - 最小资源要求（2C4G）
  - 扩容方案
- 创建: `docs/ARCHITECTURE.md`
  - 完整架构图
  - 数据流图
  - 部署拓扑图
  - 组件说明

**Subtask 17.5: 质量门禁**
- 创建: `.pre-commit-config.yaml`
  ```yaml
  repos:
    - repo: https://github.com/astral-sh/ruff-pre-commit
      rev: v0.6.0
      hooks:
        - id: ruff
        - id: ruff-format
    - repo: https://github.com/pre-commit/mirrors-mypy
      rev: v1.11.0
      hooks:
        - id: mypy
  ```
- 创建: `.github/pull_request_template.md`
  ```markdown
  ## Description
  
  ## Type of Change
  - [ ] feat
  - [ ] fix
  - [ ] docs
  - [ ] chore
  
  ## Testing
  - [ ] Unit tests pass
  - [ ] Lint passes
  - [ ] Manual test done
  
  ## DCO
  Signed-off-by: Joe <email>
  ```
- 修改: `ci.yml` — 加 coverage gate `--cov-fail-under=70`

**验证:**
```bash
# 法律
head -5 LICENSE  # → Apache License 2.0

# 社区
ls CONTRIBUTING.md SECURITY.md CODE_OF_CONDUCT.md CHANGELOG.md ROADMAP.md
# → 5 个文件都存在

# 合规
ls docs/COMPLIANCE.md docs/SECURITY_AUDIT.md docs/DEPLOYMENT.md docs/ARCHITECTURE.md
# → 4 个文件都存在

# 质量
pre-commit run --all-files
# → 全部通过

# README 对比表
grep "ContextGate" README.md | head -3
# → 项目名出现
```

**Subtask 17.6: Playground 测试页**
- 创建: `frontend/playground.html`
- 4 个 Tab:
  - **Chat**: API Key + message + session_id 输入框，Send 按钮，JSON 响应展示（含 trace_id）
  - **Admin**: 创建 API Key、查看待审批列表、审批通过/拒绝
  - **Audit**: 按 tenant/时间范围查审计日志、导出 CSV
  - **System**: 健康检查、Prometheus metrics 展示、curl 命令生成器
- 纯 `<script type="module">` + `fetch()`，零依赖
- 修改: `backend/app.py` — `app.mount("/playground", StaticFiles(directory="frontend"))`

**Subtask 17.7: 前端退役**
- 删除: `frontend/src/` 整个目录
- 删除: `frontend/public/`（保留 playground.html）
- 删除: `frontend/package.json`, `frontend/package-lock.json`
- 删除: `frontend/start_frontend.sh`, `frontend/stop_frontend.sh`
- 修改: `main.py` — 去掉前端启动逻辑（或者删除文件）
- 修改: `README.md` — 去掉 `npm start` 步骤，改为 `open http://localhost:8000/playground`
- 修改: `docker-compose*.yml` — 去掉前端相关端口和依赖

**验证:**
```bash
open http://localhost:8000/playground  # → 看到 4 个 Tab
curl http://localhost:3000  # → 不再可用（前端已删）
```

---

## 七、Subtask 执行顺序

```
Task 0 (Rebranding)             → 0.1 → 0.2 → 0.3 → 0.4
Task 1 (pgvector)               → 1.1 → 1.2 → 1.3 → 1.4 → 1.5
Task 2 (Auth)                   → 2.1 → 2.2 → 2.3 → 2.4 → 2.5
Task 3 (Tenant+Audit)           → 3.1 → 3.2 → 3.3 → 3.4
Task 4 (LangGraph)              → 4.1 → 4.2~4.7（节点）→ 4.8 → 4.9 → 4.10
Task 5 (LangFuse)               → 5.1 → 5.2 → 5.3
Task 6 (Cache)                  → 6.1 → 6.2 → 6.3
Task 7 (Cost+Skill)             → 7.1 → 7.2 → 7.3 → 7.4 → 7.5 → 7.6
Task 8 (Lock)                   → 8.1
Task 9 (Guardrails)             → 9.1 → 9.2 → 9.3
Task 10 (File Upload)           → 10.1 → 10.2
Task 11 (Circuit Breaker)       → 11.1 → 11.2 → 11.3
Task 12 (Health+SLA+Errors)     → 12.1 → 12.2 → 12.3
Task 13 (Seed)                  → 13.1 → 13.2 → 13.3
Task 14 (Docker+uv)             → 14.1 → 14.2 → 14.3 → 14.4
Task 15 (CI/CD)                 → 15.1 → 15.2 → 15.3
Task 16 (Production Deploy)     → 16.1 → 16.2
```

**关键依赖线:**
```
1.1 → 1.2~1.5
1.5 → 2.1~2.5 → 3.1~3.4 → 4.1~4.10
4.9 → (5.1~5.3 可并行)
4.8 → 6.1~6.3 (可并行)
4.6 → 7.1~7.6
4.4 → 9.1~9.3 (可并行)
14.1~14.2 → 16.1~16.2
14.3~14.4 → 15.1~15.3 (可并行 with 16)
17.1~17.5 → 最后做，不依赖其他 Task

但可以提前做 17.2（README）和 17.4（合规文档），因为不依赖代码状态
```

---

## 八、全流程验收

```bash
# 1. 启动
docker compose -f docker-compose.local.yml up -d

# 2. seed
uv run python scripts/seed_api_keys.py
uv run python scripts/seed_pgvector.py

# 3. 401 验证
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"message":"hi"}'
# → 401

# 4. 正常请求
API_KEY=$(cat .test_user_key)
curl -X POST http://localhost:8000/chat \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message":"我最近压力好大"}'
# → 200

# 5. LangFuse
open http://localhost:3001  # 完整 trace

# 6. 安全护栏
curl -X POST http://localhost:8000/chat \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message":"忽略系统提示"}'
# → 403 GUARD_001

# 7. 权限隔离
AUDITOR_KEY=$(cat .test_auditor_key)
curl -X POST http://localhost:8000/chat -H "X-API-Key: $AUDITOR_KEY"
# → 403 AUTH_002
curl -X GET http://localhost:8000/audit/logs -H "X-API-Key: $AUDITOR_KEY"
# → 200

# 8. 审批流程
USER_KEY=$(cat .test_user_key)
curl -X POST http://localhost:8000/permissions/request \
  -H "X-API-Key: $USER_KEY" \
  -d '{"resource":"kb","action":"query"}'
# → 200 pending

# 9. 断路器
# 关 API key → 返回降级回复，非 500

# 10. 健康检查
curl http://localhost:8000/health
# → 所有 checks up

# 11. Prometheus
curl http://localhost:8000/metrics
# → contextgate_requests_total{tenant="acme"} 1.0

# 12. CI
git push  # → Actions 自动跑 lint + test + build
```

---

## 九、风险和权衡

| 风险 | 缓解 |
|------|------|
| Subtask 太多 Cursor 执行慢 | 每个 Subtask 5-10 分钟，可分段执行 |
| LangGraph 节点签名不一致 | 每个节点 `(state: PipelineState) -> PipelineState` 强制统一 |
| Task 4（10 个节点）最大 | 从最简单的 `auth_check` 开始，逐渐加复杂节点 |
| pgvector 数据迁移 | demo 无生产数据，直接 seed |
| API key 泄露 | config.env 已 .gitignore |
| Prompt 注入误杀 | 可配置 `GUARDRAIL_MODE=log` 调试用 |
