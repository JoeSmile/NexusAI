"""管理接口 — API Key / 审批管理"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_permission
from backend.database.pgvector_session import get_pg_session

router = APIRouter(prefix="/admin", tags=["admin"])


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
            INSERT INTO api_keys
                (tenant_id, user_id, key_hash, key_prefix, role, description, created_by)
            VALUES (:tid, :uid, :hash, :prefix, :role, :desc, :by)
            RETURNING id, created_at
        """)
        row = session.execute(
            sql,
            {
                "tid": target_tenant,
                "uid": req.user_id,
                "hash": key_hash,
                "prefix": key_prefix,
                "role": req.role,
                "desc": req.description,
                "by": tenant.user_id,
            },
        ).fetchone()
        session.commit()

    return CreateApiKeyResponse(
        api_key=raw_key,
        key=ApiKeyResponse(
            id=row.id,
            key_prefix=key_prefix,
            role=req.role,
            tenant_id=target_tenant,
            user_id=req.user_id,
            is_active=True,
            description=req.description,
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
        if tenant.role == "super_admin":
            sql = text("UPDATE api_keys SET is_active=false WHERE id=:id")
            result = session.execute(sql, {"id": key_id})
        else:
            sql = text(
                "UPDATE api_keys SET is_active=false WHERE id=:id AND tenant_id=:tid"
            )
            result = session.execute(
                sql, {"id": key_id, "tid": tenant.tenant_id}
            )
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail={"code": "AUTH_004", "message": "api_key_not_found"},
            )
    return {"status": "deleted", "id": key_id}


@router.get("/api-keys")
async def list_api_keys(
    tenant: TenantContext = Depends(require_permission("admin:*")),
):
    """列出 API Key（不返回 key_hash）。

    当前租户默认只看本租户；super_admin（跨租户）可看全部租户。
    """
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        if tenant.is_cross_tenant:
            sql = text("""
                SELECT id, key_prefix, role, tenant_id, user_id,
                       is_active, description, created_at
                FROM api_keys
                ORDER BY created_at DESC
            """)
            rows = session.execute(sql).fetchall()
        else:
            sql = text("""
                SELECT id, key_prefix, role, tenant_id, user_id,
                       is_active, description, created_at
                FROM api_keys WHERE tenant_id = :tid
                ORDER BY created_at DESC
            """)
            rows = session.execute(sql, {"tid": tenant.tenant_id}).fetchall()
    return [
        ApiKeyResponse(
            id=r.id,
            key_prefix=r.key_prefix,
            role=r.role,
            tenant_id=r.tenant_id,
            user_id=r.user_id,
            is_active=r.is_active,
            description=r.description or "",
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
            id=r.id,
            tenant_id=r.tenant_id,
            user_id=r.user_id,
            resource=r.resource,
            resource_type=r.resource_type,
            action=r.action,
            status=r.status,
            created_at=r.created_at,
            params=r.params or {},
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
        result = session.execute(
            sql,
            {
                "status": new_status,
                "by": tenant.user_id,
                "reason": req.reason,
                "id": req.request_id,
                "tid": tenant.tenant_id,
            },
        )
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail={"code": "AUTH_004", "message": "approval_request_not_found"},
            )
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
            VALUES (
                :tid, :uid, :res, 'permission', 'approve',
                CAST(:params AS jsonb), 'pending'
            )
            RETURNING id
        """)
        row = session.execute(
            sql,
            {
                "tid": tenant.tenant_id,
                "uid": tenant.user_id,
                "res": req.resource,
                "params": json.dumps({"reason": req.reason}),
            },
        ).fetchone()
        session.commit()
    return {"status": "pending", "request_id": row.id}


# ── LLM API Key 管理 ──


class CreateLlmKeyRequest(BaseModel):
    tenant_id: str | None = None
    key_alias: str
    provider: str = "deepseek"
    base_url: str = ""
    api_key_plaintext: str
    expires_in_days: int | None = None
    description: str = ""


@router.post("/llm-keys")
async def create_llm_key(
    req: CreateLlmKeyRequest,
    tenant: TenantContext = Depends(require_permission("admin:llm_key")),
):
    """创建 LLM API Key（明文传入，加密存储）"""
    from backend.core.key_manager import KeyManager

    km = KeyManager()
    encrypted = km.encrypt(req.api_key_plaintext)
    target_tenant = req.tenant_id or tenant.tenant_id

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text(
            """
            INSERT INTO llm_api_keys
                (tenant_id, key_alias, provider, base_url, encrypted_key,
                 description, created_by, expires_at)
            VALUES
                (:tid, :alias, :prov, :url, :enc,
                 :desc, :by, now() + (:days * interval '1 day'))
            RETURNING id, created_at
            """
        )
        row = session.execute(
            sql,
            {
                "tid": target_tenant,
                "alias": req.key_alias,
                "prov": req.provider,
                "url": req.base_url,
                "enc": encrypted,
                "desc": req.description,
                "by": tenant.user_id,
                "days": req.expires_in_days or 365,
            },
        ).fetchone()
        session.commit()

    return {"id": row.id, "key_alias": req.key_alias, "status": "created"}


@router.get("/llm-keys")
async def list_llm_keys(
    tenant: TenantContext = Depends(require_permission("admin:llm_key")),
):
    """列出租户 LLM Key（不返回明文）"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        if tenant.is_cross_tenant:
            sql = text(
                """
                SELECT id, tenant_id, key_alias, provider, base_url,
                       key_version, is_active, expires_at, last_verified_ok,
                       description, created_at, rotated_at
                FROM llm_api_keys
                ORDER BY created_at DESC
                """
            )
            rows = session.execute(sql).fetchall()
        else:
            sql = text(
                """
                SELECT id, tenant_id, key_alias, provider, base_url,
                       key_version, is_active, expires_at, last_verified_ok,
                       description, created_at, rotated_at
                FROM llm_api_keys
                WHERE tenant_id = :tid
                ORDER BY created_at DESC
                """
            )
            rows = session.execute(sql, {"tid": tenant.tenant_id}).fetchall()
    return [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "key_alias": r.key_alias,
            "provider": r.provider,
            "key_version": r.key_version,
            "is_active": r.is_active,
            "last_verified_ok": r.last_verified_ok,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.delete("/llm-keys/{key_id}")
async def delete_llm_key(
    key_id: int,
    tenant: TenantContext = Depends(require_permission("admin:llm_key")),
):
    """吊销 LLM Key"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        if tenant.is_cross_tenant:
            sql = text("UPDATE llm_api_keys SET is_active=false WHERE id=:id")
            session.execute(sql, {"id": key_id})
        else:
            sql = text(
                "UPDATE llm_api_keys SET is_active=false WHERE id=:id AND tenant_id=:tid"
            )
            session.execute(sql, {"id": key_id, "tid": tenant.tenant_id})
        session.commit()
    return {"status": "deleted", "id": key_id}


@router.post("/llm-keys/{key_id}/verify")
async def verify_llm_key(
    key_id: int,
    tenant: TenantContext = Depends(require_permission("admin:llm_key")),
):
    """验证 Key 有效性"""
    from backend.core.key_health import verify_key_by_id

    return await verify_key_by_id(key_id)


@router.get("/cost-summary")
async def get_cost_summary(
    tenant_id: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    granularity: str = "day",
    tenant: TenantContext = Depends(require_permission("admin:*")),
):
    """成本聚合看板数据（来自 audit_logs）。"""
    from backend.core.cost_manager import cost_summary

    target = tenant_id
    if not tenant.is_cross_tenant:
        target = tenant.tenant_id
    if granularity not in ("day", "hour"):
        raise HTTPException(
            status_code=400,
            detail={"code": "ADMIN_001", "message": "granularity_must_be_day_or_hour"},
        )
    return cost_summary(
        tenant_id=target,
        from_ts=from_ts,
        to_ts=to_ts,
        granularity=granularity,
    )
