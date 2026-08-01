# Task 02: 认证 + RBAC0 + 应用级权限 + 审批

> **4 种角色:** super_admin / auditor / tenant_admin / user
> **认证:** `X-API-Key` → SHA256 hash → `api_keys` 表
> **前置依赖:** `tasks/01-pgvector-migration.md`（需要数据库表）
> **完成后:** 执行 `tasks/03-tenant-audit.md`
> **权限装饰器:** `require_permission(perm)` 是 **FastAPI Depends 工厂**，不是普通装饰器。

权限模型详见 `tasks/README.md` → 权限模型章节。

## Subtask 02.01: TenantContext + 权限数据模型

**文件:** `backend/core/auth/models.py`
```python
@dataclass
class TenantContext:
    tenant_id: str
    user_id: str
    role: str
    extra_permissions: list[str]
    is_cross_tenant: bool

    def has_permission(self, permission: str) -> bool:
        """支持通配符 admin:*"""
        if "admin:*" in self.extra_permissions:
            return True
        if permission in self.extra_permissions:
            return True
        role_perms = ROLES.get(self.role, {}).get("permissions", [])
        for rp in role_perms:
            if rp.endswith(":*"):
                resource = rp.split(":")[0]
                if permission.startswith(resource):
                    return True
            if rp == permission:
                return True
        return False
```

## Subtask 02.02: verify_api_key Depends — 返回 extra_permissions

**文件:** `backend/core/auth/api_key_auth.py`

返回的 `TenantContext` 现在包含 `extra_permissions`，上游 auth_check 节点会把它注入到 `state["user_context"]`，供 model_router / skill 做二级权限校验。

```python
async def verify_api_key(
    api_key: str = Security(APIKeyHeader(name="X-API-Key")),
) -> TenantContext:
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    # 查 api_keys 表，JOIN user_app_perms 获取 extra_permissions
    row = db_query("""
        SELECT ak.*, uap.permissions
        FROM api_keys ak
        LEFT JOIN user_app_perms uap ON ak.user_id = uap.user_id AND ak.tenant_id = uap.tenant_id
        WHERE ak.key_hash=:hash AND ak.is_active=true
    """, {"hash": key_hash})
    if not row:
        raise HTTPException(401, detail={"code": "AUTH_001", "message": "invalid_api_key"})
    return TenantContext(
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        role=row.role,
        extra_permissions=row.permissions or [],
        is_cross_tenant=row.role == "super_admin",
    )
```

## Subtask 02.03: require_permission + cross_tenant_only

**文件:** `backend/core/auth/permissions.py`
```python
def require_permission(permission: str):
    """返回 FastAPI Depends 函数"""
    async def _check(request: Request, tenant: TenantContext = Depends(verify_api_key)):
        if not tenant.has_permission(permission):
            raise HTTPException(403, detail={"code": "AUTH_002"})
        return tenant
    return _check

def cross_tenant_only():
    async def _check(tenant: TenantContext = Depends(verify_api_key)):
        if not tenant.is_cross_tenant:
            raise HTTPException(403, detail={"code": "AUTH_003"})
        return tenant
    return _check
```

## Subtask 02.04: 权限数据库表

**修改:** `backend/database/init_pgvector.sql` — +`api_keys`, `roles`, `user_app_perms`, `approval_requests`

`approval_requests` 表同时服务于：
- 用户申请权限（传统审批场景）
- Skill 高风险操作人工介入（Task 07 的 `requires_human_approval`）

```sql
CREATE TABLE approval_requests (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     VARCHAR(64) NOT NULL,
    user_id       VARCHAR(128) NOT NULL,
    resource      VARCHAR(256) NOT NULL,      -- 如 "tool:db_query", "skill:data_export"
    resource_type VARCHAR(32) NOT NULL DEFAULT 'permission',  -- 'permission' | 'skill' | 'tool'
    action        VARCHAR(64) NOT NULL,        -- 'approve' | 'execute'
    params        JSONB DEFAULT '{}',          -- skill 入参、申请说明等
    status        VARCHAR(16) NOT NULL DEFAULT 'pending',
                  -- pending | approved | rejected | expired
    created_at    TIMESTAMPTZ DEFAULT now(),
    timeout_at    TIMESTAMPTZ,                 -- 超时自动 expired（skill 的 approval_timeout）
    reviewed_by   VARCHAR(128),                -- 审批人
    reviewed_at   TIMESTAMPTZ,
    review_reason TEXT
);
CREATE INDEX idx_apr_tenant_status ON approval_requests(tenant_id, status);
```

**修改:** `backend/database/pgvector_session.py` — 对应 Pydantic 模型

## Subtask 02.05: admin.py — 管理 API（含 skill 审批复用）

**文件:** `backend/routers/admin.py`
- `POST /api/admin/api-keys` — 创建 key (tenant_admin)
- `DELETE /api/admin/api-keys/{id}` — 吊销 (tenant_admin)
- `GET /api/admin/pending-requests` — 待审批列表 (tenant_admin) ← **skill 人工介入也用这个**
- `POST /api/admin/approve` — 审批通过/拒绝 (tenant_admin) ← **skill 人工介入也用这个**
- `POST /api/permissions/request` — 提交权限申请 (user)

> `GET /pending-requests` 和 `POST /approve` 同时服务于两种场景：
> 1. 用户权限申请（`resource_type='permission'`）
> 2. Skill 人工介入（`resource_type='skill'`，由 `BaseSkill._create_approval_request()` 创建）
> 
> 审批通过后，前端可通知用户重试或自动重试原请求。

**修改:** `backend/app.py` — 注册 admin 路由

> **延期（不在 Task 02 / Batch 2 实现）:** SSE Streaming 治理已拆到后续任务：
> - `POST /chat/streaming` 管线转接 → **Task 04.11** / `batch-04`
> - `LLMHarness.stream()` → **Task 07.07e** / `batch-05b`
> - 流式 abort / retraction（正则）→ **Task 09.04** / `batch-05a`

## Subtask 02.06: 请求签名认证（防重放）

> **P0 安全 — 国企合规必选项。** 防止 API 请求被中间人截获后重放。
> 兼容现有 `X-API-Key` 认证，签名只做辅助验证，不改现有 auth 链路。

**文件:** `backend/core/auth/signature_auth.py`

```python
"""
HMAC-SHA256 请求签名 + 防重放中间件。

签名算法:
  string_to_sign = HTTP_METHOD + "\\n"
                 + PATH + "\\n"
                 + BODY_SHA256 (hex) + "\\n"
                 + TIMESTAMP + "\\n"
                 + NONCE
  signature = hmac_sha256(secret, string_to_sign)

Header 约定（所有请求可选，但启用签名的 key 必须携带）:
  X-CG-Access-Key-Id    — api_keys 表的 access_key_id
  X-CG-Signature        — base64(hmac_sha256)
  X-CG-Timestamp        — Unix 毫秒时间戳
  X-CG-Nonce            — UUID v4（窗口期内不可重复）
  X-CG-Signed-Headers   — 可选，签名中包含的额外 header 逗号分隔

防重放窗口: ±5 分钟（clock skew）
Nonce 去重: 内存中的 LRU cache + TTL 5 分钟（不引入 Redis）
"""

import hashlib
import hmac
import time
from collections import OrderedDict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class NonceCache:
    """非持久化 nonce 去重 — TTL 缓存"""
    MAX_SIZE = 10000
    TTL_SEC = 300  # 5 分钟

    def __init__(self):
        self._cache: OrderedDict[str, int] = OrderedDict()

    def has(self, nonce: str) -> bool:
        self._evict()
        return nonce in self._cache

    def add(self, nonce: str) -> None:
        self._cache[nonce] = int(time.time())
        if len(self._cache) > self.MAX_SIZE:
            self._cache.popitem(last=False)

    def _evict(self) -> None:
        now = int(time.time())
        stale = [k for k, v in self._cache.items() if now - v > self.TTL_SEC]
        for k in stale:
            del self._cache[k]


NONCE_CACHE = NonceCache()


async def verify_request_signature(request: Request) -> None:
    """FastAPI 中间件调用 — 在 auth_check 前执行。

    流程:
      1. 检查是否携带签名头 — 没有则跳过（向后兼容）
      2. 解析 key_id → 查 api_keys 表获得 secret
      3. 验证 timestamp 在 ±5min 内
      4. 验证 nonce 未使用
      5. 验证 signature 匹配
    """
    key_id = request.headers.get("X-CG-Access-Key-Id")
    if not key_id:
        return  # 向后兼容: 无签名头走原有 X-API-Key 认证

    signature = request.headers.get("X-CG-Signature")
    timestamp_str = request.headers.get("X-CG-Timestamp")
    nonce = request.headers.get("X-CG-Nonce")

    if not all([signature, timestamp_str, nonce]):
        raise HTTPException(400, detail={"code": "AUTH_005", "message": "missing_signature_headers"})

    # 1. 时间窗口校验
    try:
        ts_ms = int(timestamp_str)
    except ValueError:
        raise HTTPException(400, detail={"code": "AUTH_006", "message": "invalid_timestamp"})
    now_ms = int(time.time() * 1000)
    if abs(now_ms - ts_ms) > 300_000:  # 5 分钟
        raise HTTPException(401, detail={"code": "AUTH_007", "message": "signature_expired_or_future"})

    # 2. Nonce 去重
    nonce_key = f"{key_id}:{nonce}"
    if NONCE_CACHE.has(nonce_key):
        raise HTTPException(401, detail={"code": "AUTH_008", "message": "nonce_reused"})

    # 3. 查 key 的 secret
    secret = await _get_key_secret(key_id)
    if not secret:
        raise HTTPException(401, detail={"code": "AUTH_009", "message": "invalid_access_key"})

    # 4. 验证签名
    body = await request.body()
    body_hash = hashlib.sha256(body).hexdigest()
    string_to_sign = f"{request.method}\n{request.url.path}\n{body_hash}\n{timestamp_str}\n{nonce}"
    expected = hmac.new(
        secret.encode(), string_to_sign.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, detail={"code": "AUTH_010", "message": "signature_mismatch"})

    # 5. 记录 nonce
    NONCE_CACHE.add(nonce_key)
    # 注入已验证的上下文
    request.state.signature_verified = True
    request.state.signer_key_id = key_id


async def _get_key_secret(key_id: str) -> str | None:
    """从 api_keys 表查 access_key_secret

    api_keys 表新增字段:
      - access_key_id     VARCHAR(64) UNIQUE    — 签名用的 public key id
      - access_key_secret TEXT ENCRYPTED        — 签名用的 secret（见 Task 18 加密方案）
      - signature_enabled BOOLEAN DEFAULT false — 是否强制启用签名
    """
    # TODO: SQL — SELECT access_key_secret FROM api_keys
    #       WHERE access_key_id = :key_id AND is_active = true
    return None  # Cursor 实现时替换


class SignatureMiddleware(BaseHTTPMiddleware):
    """注册到 FastAPI app — 全局签名校验"""
    async def dispatch(self, request, call_next):
        try:
            await verify_request_signature(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return await call_next(request)
```

**数据库变更 — `api_keys` 表新增字段:**

```sql
ALTER TABLE api_keys
  ADD COLUMN access_key_id     VARCHAR(64) UNIQUE,
  ADD COLUMN access_key_secret TEXT,          -- 加密存储（AES-GCM, Task 18 的 KeyManager）
  ADD COLUMN signature_enabled BOOLEAN DEFAULT false,
  ADD COLUMN signature_key_version INT DEFAULT 1;
CREATE INDEX idx_api_keys_access_key_id ON api_keys(access_key_id);
```

**⚠️ Cursor 实现警告:**
- `verify_request_signature` 必须**跳过** OPTIONS / preflight 请求（CORS）
- `request.body()` 在中间件中调用后会消费流 — 必须用 `request.stream()` 或缓存 body
- 签名启用是**可选**的 — 当 `api_keys.signature_enabled=false` 时走现有 `X-API-Key` 认证
- NonceCache 是进程级内存 — 多 worker 场景每个 worker 独立，需升级到 Redis
- 测试时用 Python 生成签名: `hmac.new(secret.encode(), string_to_sign.encode(), 'sha256').hexdigest()`

**客户端签名生成示例:**
```python
import hashlib, hmac, time, uuid

def sign_request(method: str, path: str, body: bytes, secret: str) -> dict:
    ts = str(int(time.time() * 1000))
    nonce = str(uuid.uuid4())
    body_hash = hashlib.sha256(body).hexdigest()
    string_to_sign = f"{method}\n{path}\n{body_hash}\n{ts}\n{nonce}"
    sig = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).hexdigest()
    return {"X-CG-Signature": sig, "X-CG-Timestamp": ts, "X-CG-Nonce": nonce}
```

## 验证

```bash
# 无签名 — 向后兼容
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{}'
# → 401 {"code": "AUTH_001"} （现有 X-API-Key 校验）

# 签名错误
curl -X POST http://localhost:8000/chat \
  -H "X-CG-Access-Key-Id: test_key" \
  -H "X-CG-Signature: bad" \
  -H "X-CG-Timestamp: 999" \
  -H "X-CG-Nonce: xxx" \
  -d '{}'
# → 401 {"code": "AUTH_006"} 或 AUTH_007

# 正常签名（用 Python 生成后 curl）
# → 200（通过签名后走到 X-API-Key 验证）

# Nonce 重放
# 第二次发同一组 header
# → 401 {"code": "AUTH_008"}

# 钟偏测试 — timestamp 设置为 10 分钟前
# → 401 {"code": "AUTH_007"}
```
