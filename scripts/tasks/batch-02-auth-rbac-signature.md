# Batch 2: 安全骨架 — 认证 + RBAC0 + 请求签名

> **包含:** Task 02 (6 subtasks)  
> **预估:** 30-50 分钟  
> **依赖:** Batch 1 (pgvector 模型 + ApiKey 表已定义)  
> **Commit:** `git add -A && git commit -m "feat: auth + RBAC0 + request signature\n\nSigned-off-by: Joe"`
>
> **不在本 Batch:** SSE `/chat/streaming`、Harness.stream、流式 abort/retraction  
> → 已拆到 **04.11 / 07.07e / 09.04**（见 `tasks/02-auth-rbac.md` 延期说明）

---

## 架构回顾

```
4 种角色: super_admin / auditor / tenant_admin / user
认证: X-API-Key Header → SHA256 hash → api_keys 表
权限: require_permission(perm) 是 FastAPI Depends 工厂
签名: 可选 HMAC-SHA256 防重放（±5min 窗口 + nonce 去重）
```

---

## 02.01: TenantContext + 权限数据模型

### 创建目录

```bash
mkdir -p backend/core/auth
touch backend/core/__init__.py
touch backend/core/auth/__init__.py
```

### 文件: `backend/core/auth/models.py`

```python
"""认证 + 权限数据模型"""

from dataclasses import dataclass

# ── 角色权限映射 ────────────────────────────────
# super_admin: 所有权限
# auditor: 跨租户只读审计
# tenant_admin: 本租户管理
# user: 应用级权限挂载
ROLES: dict[str, dict] = {
    "super_admin": {
        "description": "跨租户管理员",
        "permissions": [
            "admin:*",          # 所有管理操作
            "audit:read",       # 审计日志读取
            "audit:export",     # 审计日志导出
        ],
    },
    "auditor": {
        "description": "跨租户审计员",
        "permissions": [
            "audit:read",
            "audit:export",
        ],
    },
    "tenant_admin": {
        "description": "租户管理员",
        "permissions": [
            "chat:*",
            "kb:*",
            "admin:approve",    # 审批权限
            "admin:llm_key",    # LLM Key 管理
        ],
    },
    "user": {
        "description": "普通用户",
        "permissions": [
            "chat:write",
            "chat:read",
        ],
    },
}


@dataclass
class TenantContext:
    """认证上下文 — 请求经过 auth 后注入"""
    tenant_id: str
    user_id: str
    role: str
    extra_permissions: list[str]
    is_cross_tenant: bool

    def has_permission(self, permission: str) -> bool:
        """权限检查 — 支持通配符 `admin:*` 和 `chat:*`"""
        # 1. 管理员通配
        if "admin:*" in self.extra_permissions:
            return True
        # 2. 直接匹配 extra_permissions
        if permission in self.extra_permissions:
            return True
        # 3. 角色默认权限
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

---

## 02.02: verify_api_key Depends

### 文件: `backend/core/auth/api_key_auth.py`

```python
"""X-API-Key 认证 — 返回 TenantContext"""

import hashlib
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader
from sqlalchemy import text
from backend.core.auth.models import TenantContext

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
) -> TenantContext:
    """验证 API Key → TenantContext"""
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_001", "message": "missing_api_key"},
        )

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    from backend.database.pgvector_session import get_pg_session
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text("""
            SELECT ak.tenant_id, ak.user_id, ak.role,
                   COALESCE(uap.permissions, '[]'::json) AS extra_permissions
            FROM api_keys ak
            LEFT JOIN user_app_perms uap
                ON ak.user_id = uap.user_id AND ak.tenant_id = uap.tenant_id
            WHERE ak.key_hash = :hash AND ak.is_active = true
              AND (ak.expires_at IS NULL OR ak.expires_at > now())
        """)
        row = session.execute(sql, {"hash": key_hash}).fetchone()

    if not row:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_001", "message": "invalid_api_key"},
        )

    extra_perms = row.extra_permissions if isinstance(row.extra_permissions, list) else []

    return TenantContext(
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        role=row.role,
        extra_permissions=extra_perms,
        is_cross_tenant=row.role == "super_admin",
    )


async def optional_api_key(
    api_key: str | None = Security(api_key_header),
) -> TenantContext | None:
    """可选认证 — 某些接口可以不传 key"""
    if not api_key:
        return None
    try:
        return await verify_api_key(api_key)
    except HTTPException:
        return None
```

---

## 02.03: require_permission + cross_tenant_only

### 文件: `backend/core/auth/permissions.py`

```python
"""权限装饰器 — 返回 FastAPI Depends 函数"""

from fastapi import Depends, HTTPException, Request
from backend.core.auth.api_key_auth import verify_api_key
from backend.core.auth.models import TenantContext


def require_permission(permission: str):
    """
    权限检查 Depends 工厂。

    用法:
        @router.post("/chat")
        async def chat(tenant: TenantContext = Depends(require_permission("chat:write"))):
            ...
    """
    async def _check(
        request: Request,
        tenant: TenantContext = Depends(verify_api_key),
    ) -> TenantContext:
        if not tenant.has_permission(permission):
            raise HTTPException(
                status_code=403,
                detail={"code": "AUTH_002", "message": "insufficient_permissions"},
            )
        # 把 tenant 注入 request.state 供后续中间件使用
        request.state.tenant_context = tenant
        return tenant
    return _check


def cross_tenant_only():
    """仅 super_admin 可访问"""
    async def _check(
        request: Request,
        tenant: TenantContext = Depends(verify_api_key),
    ) -> TenantContext:
        if not tenant.is_cross_tenant:
            raise HTTPException(
                status_code=403,
                detail={"code": "AUTH_003", "message": "cross_tenant_access_denied"},
            )
        request.state.tenant_context = tenant
        return tenant
    return _check


def require_any_permission(permissions: list[str]):
    """满足任意一个权限即可通过"""
    async def _check(
        request: Request,
        tenant: TenantContext = Depends(verify_api_key),
    ) -> TenantContext:
        for perm in permissions:
            if tenant.has_permission(perm):
                request.state.tenant_context = tenant
                return tenant
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_002", "message": "insufficient_permissions"},
        )
    return _check
```

---

## 02.04: 数据库 DDL + ORM 模型

### 文件: `backend/database/init_pgvector.sql`（追加）

```sql
-- ========== Task 02: 权限表 ==========

-- API Keys 表
CREATE TABLE IF NOT EXISTS api_keys (
    id                  SERIAL PRIMARY KEY,
    tenant_id           VARCHAR(64) NOT NULL,
    user_id             VARCHAR(128) NOT NULL,
    key_hash            VARCHAR(64) UNIQUE NOT NULL,
    key_prefix          VARCHAR(8),
    role                VARCHAR(32) NOT NULL DEFAULT 'user',
    is_active           BOOLEAN DEFAULT true,
    expires_at          TIMESTAMPTZ,
    description         TEXT DEFAULT '',
    created_by          VARCHAR(128),
    created_at          TIMESTAMPTZ DEFAULT now(),
    access_key_id       VARCHAR(64) UNIQUE,       -- 签名用
    access_key_secret   TEXT,                      -- 加密存储 (Task 18)
    signature_enabled   BOOLEAN DEFAULT false,
    signature_key_version INT DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_ak_tenant ON api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ak_access_key ON api_keys(access_key_id);

-- 角色表
CREATE TABLE IF NOT EXISTS roles (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(32) UNIQUE NOT NULL,
    permissions JSONB NOT NULL DEFAULT '[]',
    description TEXT DEFAULT ''
);

-- 用户应用权限（附加权限）
CREATE TABLE IF NOT EXISTS user_app_perms (
    id          SERIAL PRIMARY KEY,
    tenant_id   VARCHAR(64) NOT NULL,
    user_id     VARCHAR(128) NOT NULL,
    permissions JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE(tenant_id, user_id)
);

-- 审批请求表（权限申请 + Skill 人工介入）
CREATE TABLE IF NOT EXISTS approval_requests (
    id            SERIAL PRIMARY KEY,
    tenant_id     VARCHAR(64) NOT NULL,
    user_id       VARCHAR(128) NOT NULL,
    resource      VARCHAR(256) NOT NULL,
    resource_type VARCHAR(32) NOT NULL DEFAULT 'permission',
    action        VARCHAR(64) NOT NULL,
    params        JSONB DEFAULT '{}',
    status        VARCHAR(16) NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ DEFAULT now(),
    timeout_at    TIMESTAMPTZ,
    reviewed_by   VARCHAR(128),
    reviewed_at   TIMESTAMPTZ,
    review_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_apr_tenant_status ON approval_requests(tenant_id, status);

-- 初始角色数据
INSERT INTO roles (name, permissions, description) VALUES
('super_admin', '["admin:*", "audit:read", "audit:export"]', '跨租户管理员'),
('auditor',     '["audit:read", "audit:export"]', '跨租户审计员'),
('tenant_admin', '["chat:*", "kb:*", "admin:approve", "admin:llm_key"]', '租户管理员'),
('user',        '["chat:write", "chat:read"]', '普通用户')
ON CONFLICT (name) DO NOTHING;
```

> ⚠️ **Cursor 注意:** 以上 DDL 追加到已有 SQL 文件底部。`api_keys` 表与 Batch 1 的 ORM 模型定义一致。

---

## 02.05: admin.py — 管理 API

### 创建: `backend/routers/__init__.py`

```python
from backend.routers.chat import router as chat_router
from backend.routers.memory import router as memory_router
from backend.routers.feedback import router as feedback_router
from backend.routers.emotion_analysis import router as emotion_router
```

### 创建: `backend/routers/admin.py`

```python
"""管理接口 — API Key / 审批管理"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_permission
from backend.database.pgvector_session import get_pg_session

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Schema ──────────────────────────────────────
class CreateApiKeyRequest(BaseModel):
    user_id: str
    role: str = "user"
    tenant_id: str | None = None  # 默认使用当前租户
    description: str = ""


class ApiKeyResponse(BaseModel):
    id: int
    key_prefix: str
    role: str
    tenant_id: str
    user_id: str
    is_active: bool
    description: str
    created_at: datetime


class CreateApiKeyResponse(BaseModel):
    api_key: str  # 仅创建时返回一次明文
    key: ApiKeyResponse


# ── API ─────────────────────────────────────────

@router.post("/api-keys", response_model=CreateApiKeyResponse)
async def create_api_key(
    req: CreateApiKeyRequest,
    tenant: TenantContext = Depends(require_permission("admin:*")),
):
    """创建 API Key（只返回一次明文）"""
    raw_key = f"cg_{secrets.token_hex(16)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:8]
    target_tenant = req.tenant_id or tenant.tenant_id

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text("""
            INSERT INTO api_keys (tenant_id, user_id, key_hash, key_prefix, role, description, created_by)
            VALUES (:tid, :uid, :hash, :prefix, :role, :desc, :by)
            RETURNING id, created_at
        """)
        row = session.execute(sql, {
            "tid": target_tenant, "uid": req.user_id,
            "hash": key_hash, "prefix": key_prefix,
            "role": req.role, "desc": req.description,
            "by": tenant.user_id,
        }).fetchone()
        session.commit()

    return CreateApiKeyResponse(
        api_key=raw_key,
        key=ApiKeyResponse(
            id=row.id, key_prefix=key_prefix, role=req.role,
            tenant_id=target_tenant, user_id=req.user_id,
            is_active=True, description=req.description,
            created_at=row.created_at,
        ),
    )


@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: int,
    tenant: TenantContext = Depends(require_permission("admin:*")),
):
    """吊销 API Key"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text("UPDATE api_keys SET is_active=false WHERE id=:id")
        session.execute(sql, {"id": key_id})
        session.commit()
    return {"status": "deleted", "id": key_id}


@router.get("/api-keys")
async def list_api_keys(
    tenant: TenantContext = Depends(require_permission("admin:*")),
):
    """列出当前租户的 API Key（不返回 key_hash）"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text("""
            SELECT id, key_prefix, role, tenant_id, user_id,
                   is_active, description, created_at
            FROM api_keys WHERE tenant_id = :tid
            ORDER BY created_at DESC
        """)
        rows = session.execute(sql, {"tid": tenant.tenant_id}).fetchall()
    return [
        ApiKeyResponse(
            id=r.id, key_prefix=r.key_prefix, role=r.role,
            tenant_id=r.tenant_id, user_id=r.user_id,
            is_active=r.is_active, description=r.description,
            created_at=r.created_at,
        )
        for r in rows
    ]


# ── 审批 API（同时服务权限申请 + Skill 人工介入）──

class PendingRequest(BaseModel):
    id: int
    tenant_id: str
    user_id: str
    resource: str
    resource_type: str
    action: str
    status: str
    created_at: datetime
    params: dict = {}


class ApproveRequest(BaseModel):
    request_id: int
    approved: bool  # true=通过, false=拒绝
    reason: str = ""


@router.get("/pending-requests")
async def list_pending_requests(
    tenant: TenantContext = Depends(require_permission("admin:approve")),
):
    """待审批列表（权限申请 + Skill 人工介入）"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text("""
            SELECT id, tenant_id, user_id, resource, resource_type,
                   action, status, created_at, params
            FROM approval_requests
            WHERE tenant_id = :tid AND status = 'pending'
            ORDER BY created_at DESC
        """)
        rows = session.execute(sql, {"tid": tenant.tenant_id}).fetchall()
    return [
        PendingRequest(
            id=r.id, tenant_id=r.tenant_id, user_id=r.user_id,
            resource=r.resource, resource_type=r.resource_type,
            action=r.action, status=r.status,
            created_at=r.created_at, params=r.params or {},
        )
        for r in rows
    ]


@router.post("/approve")
async def approve_request(
    req: ApproveRequest,
    tenant: TenantContext = Depends(require_permission("admin:approve")),
):
    """审批通过/拒绝"""
    session_factory = get_pg_session()
    new_status = "approved" if req.approved else "rejected"
    with session_factory.Session() as session:
        sql = text("""
            UPDATE approval_requests
            SET status = :status, reviewed_by = :by,
                reviewed_at = now(), review_reason = :reason
            WHERE id = :id AND tenant_id = :tid
        """)
        session.execute(sql, {
            "status": new_status, "by": tenant.user_id,
            "reason": req.reason, "id": req.request_id,
            "tid": tenant.tenant_id,
        })
        session.commit()
    return {"status": new_status, "request_id": req.request_id}


# ── 权限申请（用户发起） ────────────

class PermissionRequest(BaseModel):
    resource: str
    reason: str = ""


@router.post("/permissions/request")
async def request_permission(
    req: PermissionRequest,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """用户提交权限申请"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text("""
            INSERT INTO approval_requests
                (tenant_id, user_id, resource, resource_type, action, params, status)
            VALUES (:tid, :uid, :res, 'permission', 'approve', :params, 'pending')
            RETURNING id
        """)
        row = session.execute(sql, {
            "tid": tenant.tenant_id,
            "uid": tenant.user_id,
            "res": req.resource,
            "params": {"reason": req.reason},
        }).fetchone()
        session.commit()
    return {"status": "pending", "request_id": row.id}
```

---

## 02.06: 请求签名认证（防重放）

### 创建: `backend/core/auth/signature_auth.py`

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

Header 约定:
  X-CG-Access-Key-Id    — api_keys 表的 access_key_id
  X-CG-Signature        — hex(hmac_sha256)
  X-CG-Timestamp        — Unix 毫秒时间戳
  X-CG-Nonce            — UUID v4（窗口期内不可重复）

防重放窗口: ±5 分钟
"""

import hashlib
import hmac
import time
from collections import OrderedDict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from sqlalchemy import text

from backend.database.pgvector_session import get_pg_session


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
    """验证请求签名 — 在 auth_check 前执行"""
    # 跳过 OPTIONS（CORS preflight）
    if request.method.upper() == "OPTIONS":
        return

    key_id = request.headers.get("X-CG-Access-Key-Id")
    if not key_id:
        return  # 向后兼容: 无签名头走现有 X-API-Key 认证

    signature = request.headers.get("X-CG-Signature")
    timestamp_str = request.headers.get("X-CG-Timestamp")
    nonce = request.headers.get("X-CG-Nonce")

    if not all([signature, timestamp_str, nonce]):
        raise HTTPException(
            status_code=400,
            detail={"code": "AUTH_005", "message": "missing_signature_headers"},
        )

    # 1. 时间窗口校验
    try:
        ts_ms = int(timestamp_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "AUTH_006", "message": "invalid_timestamp"},
        )
    now_ms = int(time.time() * 1000)
    if abs(now_ms - ts_ms) > 300_000:  # ±5 分钟
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_007", "message": "signature_expired_or_future"},
        )

    # 2. Nonce 去重
    nonce_key = f"{key_id}:{nonce}"
    if NONCE_CACHE.has(nonce_key):
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_008", "message": "nonce_reused"},
        )

    # 3. 查 key 的 secret
    secret = await _get_key_secret(key_id)
    if not secret:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_009", "message": "invalid_access_key"},
        )

    # 4. 验证签名
    # ⚠️ request.body() 会消费流，先读后缓存
    body = await request.body()
    body_hash = hashlib.sha256(body).hexdigest()
    string_to_sign = (
        f"{request.method}\n{request.url.path}\n{body_hash}\n{timestamp_str}\n{nonce}"
    )
    expected = hmac.new(
        secret.encode(), string_to_sign.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_010", "message": "signature_mismatch"},
        )

    # 5. 记录 nonce
    NONCE_CACHE.add(nonce_key)
    request.state.signature_verified = True
    request.state.signer_key_id = key_id


async def _get_key_secret(key_id: str) -> str | None:
    """从 api_keys 表查 access_key_secret"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text("""
            SELECT access_key_secret FROM api_keys
            WHERE access_key_id = :kid AND is_active = true
        """)
        row = session.execute(sql, {"kid": key_id}).fetchone()
    if row:
        return row.access_key_secret
    return None


class SignatureMiddleware(BaseHTTPMiddleware):
    """全局签名校验中间件 — 注册到 FastAPI app"""
    async def dispatch(self, request, call_next):
        try:
            await verify_request_signature(request)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail,
            )
        return await call_next(request)


# ── 客户端签名生成工具 ────────────────────

def sign_request(
    method: str,
    path: str,
    body: bytes,
    secret: str,
) -> dict[str, str]:
    """生成签名头（客户端使用）"""
    ts = str(int(time.time() * 1000))
    nonce = __import__("uuid").uuid4().hex
    body_hash = hashlib.sha256(body).hexdigest()
    string_to_sign = f"{method}\n{path}\n{body_hash}\n{ts}\n{nonce}"
    sig = hmac.new(
        secret.encode(), string_to_sign.encode(), hashlib.sha256
    ).hexdigest()
    return {
        "X-CG-Access-Key-Id": secret[:8],  # 假设 key_id = secret[:8]
        "X-CG-Signature": sig,
        "X-CG-Timestamp": ts,
        "X-CG-Nonce": nonce,
    }
```

---

## 注册到 app.py

### 修改: `backend/app.py`

```python
# 在 create_app() 开头添加:
from backend.core.auth.signature_auth import SignatureMiddleware

# 在 CORS 中间件之后注册:
app.add_middleware(SignatureMiddleware)

# 在路由注册处添加 admin 路由:
from backend.routers.admin import router as admin_router
app.include_router(admin_router, prefix="/api")
```

---

## 验证

```bash
# 1. 导入验证
uv run python -c "
from backend.core.auth.models import TenantContext, ROLES
from backend.core.auth.api_key_auth import verify_api_key
from backend.core.auth.permissions import require_permission
from backend.core.auth.signature_auth import SignatureMiddleware, sign_request
print('✅ 全部 auth 模块导入成功')
"

# 2. 权限检查单元测试
uv run python -c "
from backend.core.auth.models import TenantContext

admin = TenantContext('t1', 'u1', 'super_admin', ['admin:*'], True)
user = TenantContext('t1', 'u2', 'user', ['chat:write'], False)

assert admin.has_permission('audit:read') == True
assert user.has_permission('chat:write') == True
assert user.has_permission('admin:*') == False
assert user.has_permission('audit:read') == False  # user 角色没有 audit 权限

# 带通配符的 extra_permissions
editor = TenantContext('t1', 'u3', 'user', ['kb:*'], False)
assert editor.has_permission('kb:read') == True
assert editor.has_permission('kb:write') == True
assert editor.has_permission('chat:write') == False

print('✅ 权限检查全部通过')
"

# 3. 签名工具验证
uv run python -c "
from backend.core.auth.signature_auth import sign_request
headers = sign_request('POST', '/chat', b'{\"message\":\"hello\"}', 'test_secret_key_12345')
assert 'X-CG-Signature' in headers
assert 'X-CG-Timestamp' in headers
assert 'X-CG-Nonce' in headers
print(f'✅ 签名头生成成功: {len(headers[\"X-CG-Signature\"])} chars')
"
```
