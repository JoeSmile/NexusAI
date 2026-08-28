"""Notification inbox API (Task 44.3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from backend.modules.notification.service import list_inbox, mark_read, unread_count

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _row_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "user_id": row.user_id,
        "type": row.type,
        "channel": row.channel,
        "payload": row.payload or {},
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/inbox")
async def inbox(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    rows = list_inbox(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        limit=limit,
        offset=offset,
    )
    return {"items": [_row_dict(r) for r in rows]}


@router.get("/unread-count")
async def get_unread_count(
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    n = unread_count(tenant_id=tenant.tenant_id, user_id=tenant.user_id)
    return {"unread": n}


@router.post("/{notification_id}/read")
async def read_one(
    notification_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    ok = mark_read(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        notification_id=notification_id,
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"code": "NTF_404", "message": "notification_not_found"},
        )
    return {"ok": True, "id": notification_id}
