"""E3.3b — tenant subscription settings (tenant_config JSON)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.auth.models import TenantContext
from backend.core.workflow.subscription import get_subscription, set_subscription
from backend.database.pgvector_session import TenantConfig, get_pg_session

router = APIRouter(prefix="/api/tenant", tags=["tenant-subscription"])


class SubscriptionBody(BaseModel):
    plan: str | None = Field(default=None, max_length=64)
    expires_at: datetime | None = None


@router.put("/subscription")
async def put_subscription(
    body: SubscriptionBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    if tenant.role not in ("tenant_admin", "super_admin"):
        raise HTTPException(
            status_code=403,
            detail={"code": "SUB_403", "message": "tenant_admin_required"},
        )
    sf = get_pg_session()
    with sf.Session() as session:
        row = (
            session.query(TenantConfig)
            .filter(TenantConfig.tenant_id == tenant.tenant_id)
            .one_or_none()
        )
        if row is None:
            row = TenantConfig(tenant_id=tenant.tenant_id, config={})
            session.add(row)
        cfg = dict(row.config or {}) if isinstance(row.config, dict) else {}
        row.config = set_subscription(
            cfg,
            plan=body.plan,
            expires_at=body.expires_at,
        )
        session.commit()
        return {"ok": True, "subscription": get_subscription(row.config)}


@router.get("/subscription")
async def get_subscription_endpoint(
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        row = (
            session.query(TenantConfig)
            .filter(TenantConfig.tenant_id == tenant.tenant_id)
            .one_or_none()
        )
        cfg = dict(row.config or {}) if row and isinstance(row.config, dict) else {}
        return {"subscription": get_subscription(cfg)}
