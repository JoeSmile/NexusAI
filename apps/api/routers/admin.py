"""管理接口 — API Key / 审批管理"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from packages.security.url_guard import UrlValidationError, validate_base_url
from backend.database.pgvector_session import get_pg_session
from packages.auth.models import TenantContext
from packages.auth.permissions import require_permission

router = APIRouter(prefix="/admin", tags=["admin"])


def _guard_base_url(url: str) -> str:
    try:
        return validate_base_url(url)
    except UrlValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "SSRF_001", "message": exc.code},
        ) from exc


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
        existing_user_key = session.execute(
            text(
                """
                SELECT id FROM api_keys
                WHERE tenant_id = :tid AND user_id = :uid
                  AND COALESCE(is_active, true) = true
                LIMIT 1
                """
            ),
            {"tid": target_tenant, "uid": req.user_id},
        ).fetchone()
        if existing_user_key is None:
            try:
                from packages.workflow.subscription import (
                    SeatLimitExceeded,
                    assert_seat_available,
                )

                assert_seat_available(session, tenant_id=target_tenant, adding=1)
            except SeatLimitExceeded:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "SEAT_LIMIT",
                        "message": "seat_limit_exceeded_contact_admin",
                    },
                ) from None

        sql = text("""
            INSERT INTO api_keys
                (tenant_id, user_id, key_hash, key_prefix, role, description,
                 created_by, is_active, created_at)
            VALUES (:tid, :uid, :hash, :prefix, :role, :desc, :by, true, now())
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
                       COALESCE(is_active, true) AS is_active,
                       description,
                       COALESCE(created_at, now()) AS created_at
                FROM api_keys
                ORDER BY created_at DESC
            """)
            rows = session.execute(sql).fetchall()
        else:
            sql = text("""
                SELECT id, key_prefix, role, tenant_id, user_id,
                       COALESCE(is_active, true) AS is_active,
                       description,
                       COALESCE(created_at, now()) AS created_at
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
        if tenant.is_cross_tenant:
            # super_admin 跨租户: 看全部租户的待审批(与 list_api_keys 一致)
            sql = text("""
                SELECT id, tenant_id, user_id, resource, resource_type,
                       action, status, created_at, params
                FROM approval_requests
                WHERE status = 'pending'
                ORDER BY created_at DESC
            """)
            rows = session.execute(sql).fetchall()
        else:
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
        if tenant.is_cross_tenant:
            # super_admin 跨租户: 不按租户过滤(与 list_api_keys/pending-requests 一致)
            sql = text("""
                UPDATE approval_requests
                SET status = :status, reviewed_by = :by,
                    reviewed_at = now(), review_reason = :reason
                WHERE id = :id
            """)
            params = {
                "status": new_status,
                "by": tenant.user_id,
                "reason": req.reason,
                "id": req.request_id,
            }
        else:
            sql = text("""
                UPDATE approval_requests
                SET status = :status, reviewed_by = :by,
                    reviewed_at = now(), review_reason = :reason
                WHERE id = :id AND tenant_id = :tid
            """)
            params = {
                "status": new_status,
                "by": tenant.user_id,
                "reason": req.reason,
                "id": req.request_id,
                "tid": tenant.tenant_id,
            }
        result = session.execute(sql, params)
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
                (tenant_id, user_id, resource, resource_type, action, params, status, created_at)
            VALUES (
                :tid, :uid, :res, 'permission', 'approve',
                CAST(:params AS jsonb), 'pending', now()
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


# ── LLM API Key 管理（单模型 + purpose=chat|embedding）──


class CreateLlmKeyRequest(BaseModel):
    tenant_id: str | None = None
    key_alias: str
    provider: str = "chat"  # purpose: chat | embedding（兼容旧 deepseek/qwen → chat）
    base_url: str
    api_key_plaintext: str
    model: str | None = None
    allowed_models: list[str] | None = None
    expires_in_days: int | None = None
    description: str = ""


class PatchLlmKeyRequest(BaseModel):
    key_alias: str | None = None
    model: str | None = None
    allowed_models: list[str] | None = None
    base_url: str | None = None
    api_key_plaintext: str | None = None
    is_active: bool | None = None


def _normalize_single_model(
    *,
    model: str | None = None,
    allowed_models: list[str] | None = None,
) -> list[str]:
    candidates: list[str] = []
    if isinstance(model, str) and model.strip():
        candidates.append(model.strip())
    if allowed_models:
        candidates.extend(
            m.strip() for m in allowed_models if isinstance(m, str) and m.strip()
        )
    # de-dupe preserve order
    seen: set[str] = set()
    models: list[str] = []
    for m in candidates:
        if m not in seen:
            seen.add(m)
            models.append(m)
    if len(models) != 1:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "REQ_001",
                "message": "exactly_one_model_required",
            },
        )
    return models


def _normalize_purpose(raw: str) -> str:
    from backend.core.llm_credentials import normalize_purpose

    try:
        return normalize_purpose(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "REQ_001", "message": "unsupported_provider"},
        ) from exc


def _mask_api_key(plaintext: str, *, edge: int = 8) -> str:
    """前后各 edge 位，中间 ***；永不回传明文。"""
    s = (plaintext or "").strip()
    if not s:
        return ""
    if len(s) <= edge * 2:
        return f"{s[:1]}***{s[-1:]}"
    return f"{s[:edge]}***{s[-edge:]}"


def _llm_key_row_dict(r) -> dict:
    allowed = r.allowed_models if hasattr(r, "allowed_models") else []
    if isinstance(allowed, str):
        try:
            allowed = json.loads(allowed)
        except json.JSONDecodeError:
            allowed = []
    allowed_list = allowed or []
    model = next(
        (m for m in allowed_list if isinstance(m, str) and m.strip()),
        None,
    )
    purpose = str(r.provider)
    try:
        from backend.core.llm_credentials import normalize_purpose

        purpose = normalize_purpose(purpose)
    except ValueError:
        purpose = "chat" if purpose != "embedding" else "embedding"

    key_preview = ""
    enc = getattr(r, "encrypted_key", None)
    if enc:
        try:
            from backend.core.key_manager import KeyManager

            key_preview = _mask_api_key(KeyManager().decrypt(enc), edge=8)
        except Exception:
            key_preview = ""

    return {
        "id": r.id,
        "tenant_id": r.tenant_id,
        "key_alias": r.key_alias,
        "provider": purpose,
        "purpose": purpose,
        "base_url": getattr(r, "base_url", None),
        "model": model,
        "allowed_models": allowed_list,
        "key_preview": key_preview,
        "owner_user_id": getattr(r, "owner_user_id", None),
        "key_version": r.key_version,
        "is_active": r.is_active,
        "last_verified_ok": r.last_verified_ok,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "embedding_dimensions": 1536 if purpose == "embedding" else None,
    }


def _check_duplicate_active_model(
    session,
    *,
    tenant_id: str,
    purpose: str,
    model: str,
    exclude_id: int | None = None,
) -> None:
    """Same tenant + purpose + model name among active keys → 409."""
    from backend.core.llm_credentials import is_chat_purpose, is_embedding_purpose

    sql = text(
        """
        SELECT id, provider, allowed_models FROM llm_api_keys
        WHERE tenant_id = :tid AND is_active = true
          AND owner_user_id IS NULL
          AND (:exclude_id IS NULL OR id != :exclude_id)
        """
    )
    rows = session.execute(
        sql,
        {"tid": tenant_id, "exclude_id": exclude_id},
    ).fetchall()
    for row in rows:
        prov = str(row.provider)
        if purpose == "embedding":
            if not is_embedding_purpose(prov):
                continue
        else:
            if not is_chat_purpose(prov):
                continue
        allowed = row.allowed_models or []
        if isinstance(allowed, str):
            try:
                allowed = json.loads(allowed)
            except json.JSONDecodeError:
                allowed = []
        if not isinstance(allowed, list):
            continue
        for raw in allowed:
            if isinstance(raw, str) and raw.strip() == model:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "LLM_KEY_003", "message": "duplicate_model"},
                )


@router.post("/llm-keys")
async def create_llm_key(
    req: CreateLlmKeyRequest,
    tenant: TenantContext = Depends(require_permission("admin:llm_key")),
):
    """创建单条凭证：备注名 + Key + 模型名 + Base URL；provider=chat|embedding。"""
    from backend.core.key_manager import KeyManager

    purpose = _normalize_purpose(req.provider)
    allowed_models = _normalize_single_model(
        model=req.model, allowed_models=req.allowed_models
    )
    raw_url = (req.base_url or "").strip()
    if not raw_url:
        raise HTTPException(
            status_code=400,
            detail={"code": "REQ_001", "message": "base_url_required"},
        )
    base_url = _guard_base_url(raw_url)
    if not (req.api_key_plaintext or "").strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "REQ_001", "message": "api_key_required"},
        )

    km = KeyManager()
    encrypted = km.encrypt(req.api_key_plaintext)
    target_tenant = req.tenant_id or tenant.tenant_id

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        _check_duplicate_active_model(
            session,
            tenant_id=target_tenant,
            purpose=purpose,
            model=allowed_models[0],
        )
        sql = text(
            """
            INSERT INTO llm_api_keys
                (tenant_id, key_alias, provider, base_url, encrypted_key,
                 allowed_models, owner_user_id, description, created_by, expires_at,
                 is_active)
            VALUES
                (:tid, :alias, :prov, :url, :enc,
                 CAST(:models AS jsonb), NULL, :desc, :by,
                 now() + (:days * interval '1 day'), true)
            RETURNING id, created_at
            """
        )
        row = session.execute(
            sql,
            {
                "tid": target_tenant,
                "alias": req.key_alias,
                "prov": purpose,
                "url": base_url,
                "enc": encrypted,
                "models": json.dumps(allowed_models),
                "desc": req.description,
                "by": tenant.user_id,
                "days": req.expires_in_days or 365,
            },
        ).fetchone()
        session.commit()

    return {
        "id": row.id,
        "key_alias": req.key_alias,
        "provider": purpose,
        "status": "created",
    }


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
                       allowed_models, owner_user_id, key_version, is_active,
                       expires_at, last_verified_ok, description, created_at, rotated_at,
                       encrypted_key
                FROM llm_api_keys
                ORDER BY created_at DESC
                """
            )
            rows = session.execute(sql).fetchall()
        else:
            sql = text(
                """
                SELECT id, tenant_id, key_alias, provider, base_url,
                       allowed_models, owner_user_id, key_version, is_active,
                       expires_at, last_verified_ok, description, created_at, rotated_at,
                       encrypted_key
                FROM llm_api_keys
                WHERE tenant_id = :tid
                ORDER BY created_at DESC
                """
            )
            rows = session.execute(sql, {"tid": tenant.tenant_id}).fetchall()
    return [_llm_key_row_dict(r) for r in rows]


@router.patch("/llm-keys/{key_id}")
async def patch_llm_key(
    key_id: int,
    req: PatchLlmKeyRequest,
    tenant: TenantContext = Depends(require_permission("admin:llm_key")),
):
    """更新凭证元数据（可选轮换明文 key）；不可改 purpose。"""
    from backend.core.key_manager import KeyManager

    params: dict[str, object] = {"id": key_id}

    if req.model is not None or req.allowed_models is not None:
        params["models"] = json.dumps(
            _normalize_single_model(model=req.model, allowed_models=req.allowed_models)
        )

    if req.base_url is not None:
        raw_url = req.base_url.strip()
        if not raw_url:
            raise HTTPException(
                status_code=400,
                detail={"code": "REQ_001", "message": "base_url_required"},
            )
        params["url"] = _guard_base_url(raw_url)

    if req.key_alias is not None:
        alias = req.key_alias.strip()
        if not alias:
            raise HTTPException(
                status_code=400,
                detail={"code": "REQ_001", "message": "key_alias_required"},
            )
        params["alias"] = alias

    if req.api_key_plaintext is not None:
        if not req.api_key_plaintext.strip():
            raise HTTPException(
                status_code=400,
                detail={"code": "REQ_001", "message": "api_key_required"},
            )
        km = KeyManager()
        params["enc"] = km.encrypt(req.api_key_plaintext)

    if req.is_active is not None:
        params["active"] = req.is_active

    if len(params) == 1:
        raise HTTPException(
            status_code=400,
            detail={"code": "REQ_001", "message": "no_fields_to_update"},
        )

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        lookup_sql = text(
            """
            SELECT id, tenant_id, provider, is_active, allowed_models
            FROM llm_api_keys
            WHERE id = :id
              AND (:cross OR tenant_id = :tid)
            """
        )
        existing = session.execute(
            lookup_sql,
            {
                "id": key_id,
                "cross": tenant.is_cross_tenant,
                "tid": tenant.tenant_id,
            },
        ).fetchone()
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "AUTH_004", "message": "llm_key_not_found"},
            )

        purpose = _normalize_purpose(str(existing.provider))
        model_for_dup: str | None = None
        if "models" in params:
            model_for_dup = json.loads(str(params["models"]))[0]
        else:
            allowed = existing.allowed_models or []
            if isinstance(allowed, str):
                try:
                    allowed = json.loads(allowed)
                except json.JSONDecodeError:
                    allowed = []
            if isinstance(allowed, list):
                for raw in allowed:
                    if isinstance(raw, str) and raw.strip():
                        model_for_dup = raw.strip()
                        break

        activating = req.is_active is True or (
            req.is_active is None and existing.is_active
        )
        if activating and model_for_dup:
            _check_duplicate_active_model(
                session,
                tenant_id=str(existing.tenant_id),
                purpose=purpose,
                model=model_for_dup,
                exclude_id=key_id,
            )

        set_parts: list[str] = []
        if "models" in params:
            set_parts.append("allowed_models = CAST(:models AS jsonb)")
        if "url" in params:
            set_parts.append("base_url = :url")
        if "enc" in params:
            set_parts.append("encrypted_key = :enc")
        if "active" in params:
            set_parts.append("is_active = :active")
        if "alias" in params:
            set_parts.append("key_alias = :alias")

        sql = text(
            f"UPDATE llm_api_keys SET {', '.join(set_parts)} WHERE id = :id"
        )
        session.execute(sql, params)
        session.commit()

    return {"status": "updated", "id": key_id}


@router.delete("/llm-keys/{key_id}")
async def delete_llm_key(
    key_id: int,
    tenant: TenantContext = Depends(require_permission("admin:llm_key")),
):
    """Permanently remove an LLM key row (encrypted secret erased; not listed again)."""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        if tenant.is_cross_tenant:
            sql = text("DELETE FROM llm_api_keys WHERE id = :id RETURNING id")
            params: dict[str, object] = {"id": key_id}
        else:
            sql = text(
                "DELETE FROM llm_api_keys WHERE id = :id AND tenant_id = :tid RETURNING id"
            )
            params = {"id": key_id, "tid": tenant.tenant_id}
        row = session.execute(sql, params).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "AUTH_004", "message": "llm_key_not_found"},
            )
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
    from packages.cost_manager import cost_summary

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
