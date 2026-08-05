# 04a — 深挖 A：认证 · RBAC · 作用域

> 面试目标：一条请求从 Header 到 `TenantContext` 到权限串到「能不能碰别人的 user_id」讲清楚；说清三条入口如何共用钥匙；诚实讲密码登录只是「取 key 的门」。  
> 锚点：`api_key_auth.py` · `models.py` · `permissions.py` · `scope.py` · `signature_auth.py` · `routers/auth.py` · `password.py`  
> 对照：B/C/D 入口都挂在这套身份上 → [05b](05b-pipeline-nodes.md) / [07c](07c-harness-cost-shortpath.md) / [09d](09d-rag-capability.md)

---

## 0. 总览图

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

**面试纠正话术：**  
「我们没有把整站改成 JWT。密码只是测试/人机友好的取 key 通道，授权真相仍是 api_keys + RBAC。」

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

## 8) 三条产品入口如何共用身份

```text
/chat          → require_permission("chat:write") → TenantContext → pipeline state.user_context
/api/rag/ask   → _rag_guard（基于 TenantContext）→ ask(..., tenant_id, user_id)
/api/capabilities/* → verify_api_key → 动态 permission / 可见性
```

租户隔离字段：`tenant_id` 贯穿 cache key、memory、LLM key 链、审计。  
跨租户：只有 `is_cross_tenant` 角色看全租户审计等；写他人资源仍受 `resolve_acting_user_id` 约束（auditor 只读）。

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
6. 密码和 key 关系？→ 密码换 key，不是平行会话体系  
7. 签名解决什么？→ 防篡改 + 防重放  

### 求职者 60 秒

> 认证是 X-API-Key 哈希查库得到租户上下文；四角色给默认权限，应用级权限表可加挂，通配符 `resource:*`。  
> 路由用 Depends 做固定权限；能力市场按条目鉴权。  
> 另有 user 作用域防 IDOR，以及可选 HMAC 签名。  
> 最近补了账号密码登录，只为签发同一套 cg_ key，治理面不分裂。

---

## 10) 还能怎么更好（Auth 域）

| 优先级 | 点 | 方向 |
|--------|----|------|
| P0 | Key 轮换/泄露应急 | 已有登录轮换；补管理面一键吊销 + 审计 |
| P1 | 权限模型文档化 | 矩阵表进 SECURITY.md（角色 × API） |
| P1 | 签名 Nonce 持久化 | 多实例下内存 NonceCache 不够，需 Redis |
| P2 | SSO / OIDC | 国企常见；仍应映射到内部 TenantContext+key 或等价会话 |
| P2 | 细粒度 kb/rag permission | user 默认无 kb:*，产品化时挂载策略要清晰 |

---

## 11) 自测

1. 默写四角色 × 跨租户 × 各 2 个权限串  
2. 画出 verify → require_permission → attach 的 Depends 链  
3. auditor 能否 `resolve_acting_user_id` 覆写他人？→ 不能  
4. 注册成功后 FE 下一步用什么调 `/chat`？→ 返回的 cg_ key  

```bash
sed -n '32,71p' backend/core/auth/api_key_auth.py
sed -n '12,78p' backend/core/auth/models.py
sed -n '16,37p' backend/core/auth/permissions.py
sed -n '10,70p' backend/core/auth/scope.py
```

---

## 12) 衔接

- B/C/D 已写完；A 是共用地基  
- 建议串讲顺序：**A → B → C**，穿插 **D** 讲 Hub 例外  
- Demo：四角色 key 各打一枪（chat / audit / 跨租户拒绝）
