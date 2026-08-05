# 04a — 深挖 A：认证 · RBAC · 作用域

> 面试目标：讲清 **现状** Header→TenantContext→权限串；并主动对比 **目标双轨**（JWT∥machine Key）与 **组织 B**。  
> 锚点：`api_key_auth.py` · `models.py` · `permissions.py` · `scope.py` · `signature_auth.py` · `routers/auth.py` · `password.py`  
> **目标叙事：** [02](02-runtime-split.md) · [03](03-org-security.md) · [pilot-b §9/§11](../docs/superpowers/specs/2026-08-05-enterprise-pilot-b-gaps-design.md)  
> 对照管线/Hub：[05b](05b-pipeline-nodes.md) / [09d](09d-rag-capability.md)

---

## 0. 现状 vs 目标（先背这张表）

| | **现状（代码）** | **目标（已签核）** |
|--|------------------|-------------------|
| 人 | 密码登录发 `cg_`，FE 当会话 | 登录发 **JWT**；`verify_session` |
| 机 | 同一套 `X-API-Key` | 仅 `credential_type=machine` 的 Key |
| 上下文 | `TenantContext`：tenant/user/role/extra | + `credential_kind` / 强化 `acting_user_id` / OrgScope |
| 组织 | 无部门 | 部门树 + 业务角色（§11） |
| 密码定位 | 「取 key 的门」 | 「取会话 JWT 的门」 |

下文 §1–§8 以 **现状代码** 为准；演进见文末 §10。

---

## 0b. 总览图（现状）

```text
┌─ 可选：HMAC 签名中间件（X-CG-*，防重放）─────────────────┐
│                                                         │
│  X-API-Key: cg_…                                        │
│       │                                                 │
│       ▼                                                 │
│  SHA256 → api_keys（is_active / expires）                │
│       + LEFT JOIN user_app_perms → extra_permissions    │
│       ▼                                                 │
│  TenantContext{tenant_id, user_id, role,                │
│                extra_permissions, is_cross_tenant}      │
│       │                                                 │
│       ├─ Depends(require_permission("…"))  → AUTH_002   │
│       ├─ Depends(verify_api_key) only      → Hub 动态权  │
│       ├─ cross_tenant_only()               → AUTH_003   │
│       └─ assert_user_access / resolve_acting_user_id    │
│              → AUTH_004（防 IDOR）                        │
└─────────────────────────────────────────────────────────┘

密码登录（Task 38，旁路）：
  POST /api/auth/login|register
    → bcrypt 校验/注册
    → 签发或轮换 cg_ key（明文仅一次）
    → 之后一切仍走 X-API-Key，不引入平行 JWT 世界
```

**一句话：**  
密钥是唯一通行凭证；角色给默认权限包；`user_app_perms` 可加挂；跨租户只有 `super_admin`/`auditor`；密码只是「怎么拿到 key」。

---

## 1) API Key 认证（主干）

文件：`backend/core/auth/api_key_auth.py`

| 步骤 | 行为 |
|------|------|
| Header | `X-API-Key`（`APIKeyHeader`，缺省不自动 403，手写检查） |
| 缺 key | 401 `AUTH_001` missing_api_key |
| 存储 | **只存 SHA256**，库内无明文 |
| 查询 | `api_keys` active + 未过期；拼 `user_app_perms.permissions` JSON |
| 成功 | 构造 `TenantContext`；`is_cross_tenant = role ∈ {super_admin, auditor}` |
| 无效 | 401 `AUTH_001` invalid_api_key |

`optional_api_key`：无 key / 无效时返回 `None`（少数公开面）。

**面试陷阱：** 「key 存在数据库里」——要纠正为「只存 hash」。

---

## 2) 四角色与权限匹配

文件：`backend/core/auth/models.py`

| 角色 | 跨租户？ | 默认权限包（摘要） |
|------|----------|-------------------|
| `super_admin` | ✅ | `admin:*`（匹配一切）、`audit:read/export` |
| `auditor` | ✅ | 仅 `audit:read/export`（只读审计） |
| `tenant_admin` | ❌ | `chat:*`、`kb:*`、`admin:approve`、`admin:llm_key` |
| `user` | ❌ | `chat:write`、`chat:read` |

### 匹配规则 `_perm_matches`

1. `admin:*` → 全能  
2. 精确相等  
3. `resource:*` → 匹配同 resource 下任意 action（及裸 resource 名）  
4. `extra_permissions` **先于** 角色包检查（挂载权限可放宽）

`has_permission` = extra ∪ 角色包。

**场景题：**  
user 有没有 `kb:write`？默认没有 → 要 `user_app_perms` 加挂或升 `tenant_admin`。  
auditor 能不能调 `/chat`？默认角色包无 `chat:write` → 403，除非 extra 挂了。

---

## 3) Depends 工厂（怎么挂到路由）

文件：`permissions.py`（`require_permission` fan-in ~67，图上热点）

| 工厂 | 用途 | 失败码 |
|------|------|--------|
| `require_permission(p)` | 先验 key，再 `has_permission(p)` | AUTH_002 |
| `require_any_permission([...])` | 任一即可 | AUTH_002 |
| `cross_tenant_only()` | 必须 `is_cross_tenant` | AUTH_003 |

成功时 `_attach_tenant` → `request.state.tenant_context`。

### 与 Capability 例外（对照 D）

| 模式 | 用法 |
|------|------|
| 常规 | `Depends(require_permission("chat:write"))` |
| Hub | `Depends(verify_api_key)` + 每条 `spec.permission` / 租户可见性 |

**口述：** 「固定权限串走装饰器；能力市场权限按条目变化，所以 Hub 动态闸。」

---

## 4) 作用域 — 防 IDOR（常被忽略的加分项）

文件：`scope.py`

| API | 含义 |
|-----|------|
| `can_access_user` / `assert_user_access` | path/body 里的 `user_id` 必须是本人，或跨租户/tenant_admin/super_admin/`admin:*` |
| `resolve_acting_user_id` | 默认操作自己；**仅** tenant_admin/super_admin/`admin:*` 可覆写他人；**auditor 不可代写** |
| `require_tenant_admin` | 遗忘权、清缓存等破坏性运维 |

失败：403 `AUTH_004` user_scope_denied。

**面试故事：**  
「认证解决你是谁；RBAC 解决你能调哪个 API；scope 解决你能不能动这个 user_id 的数据——三层。」

---

## 5) 签名认证（企业向第二道门）

文件：`signature_auth.py`

- 算法：HMAC-SHA256 over `METHOD\nPATH\nBODY_SHA256\nTIMESTAMP\nNONCE`  
- Header：`X-CG-Access-Key-Id` / `X-CG-Signature` / `X-CG-Timestamp` / `X-CG-Nonce`  
- 窗口：±5 分钟；NonceCache 防重放  
- 典型错误：`AUTH_005` 缺头、`AUTH_007` 过期、`AUTH_010` mismatch  

**定位：** 开放 API / 机机调用加固；与「人用 X-API-Key」可并存。面试提一句「有防重放签名层」即可，别喧宾夺主。

---

## 6) 密码登录（Task 38）— 门，不是第二套认证

| 点 | 事实 |
|----|------|
| 端点 | `POST /api/auth/register`、`/login`（自身无全局 Depends） |
| 密码 | bcrypt cost=12，`password.py` |
| 成功 | 下发 `cg_…` 明文一次；DB 只留 hash；登录**轮换**旧 key |
| 防爆破 | 失败计数（redis / 内存降级）→ 429 |
| 审计 | `auth.register` / `auth.login` |
| 下游 | FE 把 key 放进原有槽位；面板仍全部 `X-API-Key` |

**面试纠正话术（现状）：**  
「当前密码只换同一套 cg_ key，尚未上 JWT——这是已知债；目标是人 JWT / 机 Key 分轨（pilot-b §9）。」

**目标话术：** 密码/SSO → JWT 会话；机器集成单独发 machine key；不再把长期 key 塞给浏览器。

---

## 7) 错误码速查

| Code | HTTP | 含义 |
|------|------|------|
| AUTH_001 | 401 | 缺/错 API Key |
| AUTH_002 | 403 | 权限不足 |
| AUTH_003 | 403 | 需要跨租户角色 |
| AUTH_004 | 403 | user 作用域 / IDOR |
| AUTH_005/007/010 | 4xx | 签名头/过期/不匹配 |
| CAP_001（Hub） | — | 能力不可见时装 not found（见 D） |

---

## 8) 三条产品入口如何共用身份（现状）

```text
/chat          → require_permission("chat:write") → TenantContext → pipeline
/api/rag/ask   → TenantContext → RAG
/api/capabilities/* → verify_api_key → 动态 permission
```

**目标：** Chat/工作台走人会话；capability 单次 invoke 可机调；**多节点编排走 Runner**（[06](06-workflow-runner.md)），不再默认知「一切进 /chat」。

租户隔离字段：`tenant_id` 贯穿 cache、memory、key 链、审计。  
目标另加 **OrgScope**（部门子树）——见 [03](03-org-security.md)。

---

## 9) 三维速记

### 图
- Hotspot：`require_permission` fan-in 极高；`assert_user_access` 次之  
- 边界：几乎所有 `routers→core.auth`

### 面试官爱问

1. key 明文存哪？→ 不存，只存 SHA256；登录返回仅一次  
2. 四角色差异？→ 表背 + auditor 跨租户只读  
3. `chat:*` 能覆盖 `chat:write` 吗？→ 能（通配）  
4. user 改别人 session？→ AUTH_004  
5. Hub 为何不用 require_permission？→ 动态权限（D）  
6. 密码和 key 关系？→ **现状** 密码换 key；**目标** 密码换 JWT，机单独 Key  
7. 签名解决什么？→ 防篡改 + 防重放（偏机机）  
8. 为何还要业务角色？→ 平台角色不够表达「部门经理批本部门」（[03](03-org-security.md)）

### 求职者 60 秒

> **现状：** X-API-Key 哈希查库得 TenantContext；四角色 + extra 加挂；Depends 与 Hub 动态权。  
> **目标：** 人 JWT / 机 Key；组织树 + 业务角色 + OrgScope；挂起等批先过 S1–S4。  
> 密码登录今天只换 key——这是演进起点，不是终局。

---

## 10) 还能怎么更好（Auth 域 · 对齐签核）

| 优先级 | 点 | 方向 |
|--------|----|------|
| **P0** | 人机凭证拆分 | JWT + machine-only Key；§9 M1–M6 |
| **P0** | 组织 B + OrgScope | 部门树、业务角色；所有过滤单一门面 |
| **P0** | S1–S4 | 挂起前必须满足；否则只失败不申请 |
| P1 | Key 吊销 / 轮换管理面 | 审计完整 |
| P1 | 签名 Nonce Redis | 多实例 |
| P2 | SSO / OIDC | 映射到 JWT + TenantContext |
| P2 | 细粒度 kb 权限 | 产品化挂载策略 |

---

## 11) 自测

1. 默写四平台角色 × 跨租户  
2. 画出 **现状** verify_api_key 链，再说目标 verify_session  
3. auditor 能否覆写他人 user_id？→ 不能  
4. 注册成功后 **今天** FE 用什么调 API？→ cg_ key；**目标**？→ JWT  

---

## 12) 衔接

- 目标运行时 → [02](02-runtime-split.md) · 组织安全 → [03](03-org-security.md)  
- 串讲：**02/03 → A(本篇现状) → 06 Runner → 05b Chat**  
- Demo：四角色各打一枪；能讲清「这是现状单钥匙」加分
