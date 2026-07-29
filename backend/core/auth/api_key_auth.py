"""X-API-Key 认证 — 返回 TenantContext"""

from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import text

from backend.core.auth.models import TenantContext

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _parse_permissions(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(p) for p in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(p) for p in parsed]
    return []


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

    return TenantContext(
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        role=row.role,
        extra_permissions=_parse_permissions(row.extra_permissions),
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
