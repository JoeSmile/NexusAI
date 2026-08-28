"""Terms version + acceptance APIs (Task 55 slice 3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from backend.core.billing.context import get_billing_context
from backend.core.terms.service import (
    get_current_terms,
    list_pending_terms,
    record_acceptance,
)
from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext

router = APIRouter(prefix="/terms", tags=["terms"])


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


@router.get("/current")
async def terms_current(
    kind: str = Query(..., description="company_key|byok|privacy|general"),
):
    """当前有效条款（公开可读）。"""
    doc = get_current_terms(kind)
    if doc is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=404,
            detail={"code": "TERMS_002", "message": "terms_not_found"},
        )
    return doc


@router.get("/pending")
async def terms_pending(
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
):
    """当前用户尚未同意的条款列表。"""
    ctx = get_billing_context()
    return {
        "pending": list_pending_terms(
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            credential_kind=ctx.credential_kind,
        )
    }


@router.post("/accept")
async def terms_accept(
    request: Request,
    body: dict,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
):
    """记录用户对指定 kind+version 的同意。"""
    kind = str(body.get("kind") or "").strip()
    version = str(body.get("version") or "").strip()
    if not kind or not version:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail={"code": "TERMS_003", "message": "kind_and_version_required"},
        )
    return record_acceptance(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        kind=kind,
        version=version,
        ip_address=_client_ip(request),
    )
