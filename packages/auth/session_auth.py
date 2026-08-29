"""Bearer JWT session auth → TenantContext(credential_kind=human_session)."""

from __future__ import annotations

import json

from fastapi import Header, HTTPException
from sqlalchemy import text

from packages.auth.jwt_session import verify_access_token
from packages.auth.models import TenantContext


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


def _load_extra_permissions(*, user_id: str, tenant_id: str) -> list[str]:
    from packages.database.pgvector_session import get_pg_session

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        row = session.execute(
            text("""
                SELECT permissions FROM user_app_perms
                WHERE user_id = :uid AND tenant_id = :tid
            """),
            {"uid": user_id, "tid": tenant_id},
        ).fetchone()
    if not row:
        return []
    return _parse_permissions(row.permissions)


async def verify_session(
    authorization: str | None = Header(None),
) -> TenantContext:
    """Bearer <jwt> → TenantContext(human_session)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_001", "message": "missing_bearer_token"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_001", "message": "missing_bearer_token"},
        )

    try:
        claims = verify_access_token(token)
    except ValueError as exc:
        msg = str(exc) or "invalid_token"
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_001", "message": msg},
        ) from exc

    sub = str(claims["sub"])
    tid = str(claims["tid"])
    role = str(claims["role"])
    extras = _load_extra_permissions(user_id=sub, tenant_id=tid)

    return TenantContext(
        tenant_id=tid,
        user_id=sub,
        role=role,
        extra_permissions=extras,
        is_cross_tenant=role in ("super_admin", "auditor"),
        credential_kind="human_session",
        key_id=None,
        acting_user_id=sub,
    )
