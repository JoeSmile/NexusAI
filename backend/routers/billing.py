"""Billing usage APIs (Task 55 slice 1)."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.auth.models import TenantContext
from backend.core.billing.wallet import get_wallet_summary, recharge_wallet
from backend.database.pgvector_session import get_pg_session

router = APIRouter(prefix="/billing", tags=["billing"])


def _can_read_billing(tenant: TenantContext) -> bool:
    if tenant.has_permission("admin:*"):
        return True
    return tenant.role in ("tenant_admin", "auditor", "super_admin")


def _resolve_tenant_id(tenant: TenantContext, requested: str | None) -> str | None:
    if tenant.is_cross_tenant:
        return requested
    return tenant.tenant_id


def _can_manage_wallet(tenant: TenantContext) -> bool:
    if tenant.has_permission("admin:*"):
        return True
    return tenant.role in ("tenant_admin", "super_admin")


class WalletRechargeBody(BaseModel):
    amount: float = Field(..., gt=0)
    reference_no: str = Field(..., min_length=1, max_length=128)
    tenant_id: str | None = None
    method: str = "manual"


@router.get("/wallet")
async def wallet_status(
    tenant_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
):
    """余额 + 流水分页。"""
    if not _can_read_billing(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "BILLING_001", "message": "billing_read_denied"},
        )
    tid = _resolve_tenant_id(tenant, tenant_id)
    if not tid:
        raise HTTPException(
            status_code=400,
            detail={"code": "BILLING_004", "message": "tenant_id_required"},
        )
    return get_wallet_summary(tid, limit=limit, offset=offset)


@router.post("/wallet/recharge")
async def wallet_recharge(
    body: WalletRechargeBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
):
    """人工入账（对公转账核对后 admin 充值）。"""
    if not _can_manage_wallet(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "BILLING_005", "message": "billing_recharge_denied"},
        )
    tid = body.tenant_id if tenant.is_cross_tenant else tenant.tenant_id
    if tenant.is_cross_tenant and not body.tenant_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "BILLING_004", "message": "tenant_id_required"},
        )
    try:
        return recharge_wallet(
            tenant_id=tid,
            amount=body.amount,
            reference_no=body.reference_no.strip(),
            operator=tenant.user_id,
            method=body.method,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "BILLING_006", "message": str(e)},
        ) from e


@router.get("/usage/summary")
async def usage_summary(
    tenant_id: str | None = Query(None),
    billing_month: str | None = Query(None, description="YYYY-MM"),
    credential_kind: str | None = Query(None, description="company|byok"),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
):
    """按租户/月份/模型聚合消费。"""
    if not _can_read_billing(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "BILLING_001", "message": "billing_read_denied"},
        )

    tid = _resolve_tenant_id(tenant, tenant_id)
    clauses = ["1=1"]
    params: dict[str, object] = {}
    if tid:
        clauses.append("tenant_id = :tid")
        params["tid"] = tid
    if billing_month:
        clauses.append("billing_month = :bm")
        params["bm"] = billing_month
    if credential_kind:
        clauses.append("credential_kind = :ck")
        params["ck"] = credential_kind
    where = " AND ".join(clauses)

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        by_model = session.execute(
            text(
                f"""
                SELECT model,
                       credential_kind,
                       COUNT(*) AS calls,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(cost), 0) AS cost
                FROM usage_records
                WHERE {where}
                GROUP BY model, credential_kind
                ORDER BY cost DESC
                """
            ),
            params,
        ).fetchall()
        totals = session.execute(
            text(
                f"""
                SELECT COUNT(*) AS calls,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(cost), 0) AS cost
                FROM usage_records
                WHERE {where}
                """
            ),
            params,
        ).fetchone()

    return {
        "tenant_id": tid,
        "billing_month": billing_month,
        "credential_kind": credential_kind,
        "totals": {
            "calls": int(totals.calls or 0) if totals else 0,
            "input_tokens": int(totals.input_tokens or 0) if totals else 0,
            "output_tokens": int(totals.output_tokens or 0) if totals else 0,
            "cost": float(totals.cost or 0.0) if totals else 0.0,
        },
        "by_model": [
            {
                "model": r.model,
                "credential_kind": r.credential_kind,
                "calls": int(r.calls),
                "input_tokens": int(r.input_tokens),
                "output_tokens": int(r.output_tokens),
                "cost": float(r.cost),
            }
            for r in by_model
        ],
    }


@router.get("/usage/detail")
async def usage_detail(
    tenant_id: str | None = Query(None),
    billing_month: str | None = Query(None),
    credential_kind: str | None = Query(None),
    model: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
):
    """分页消费明细。"""
    if not _can_read_billing(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "BILLING_001", "message": "billing_read_denied"},
        )

    tid = _resolve_tenant_id(tenant, tenant_id)
    clauses = ["1=1"]
    params: dict[str, object] = {"lim": limit, "off": offset}
    if tid:
        clauses.append("tenant_id = :tid")
        params["tid"] = tid
    if billing_month:
        clauses.append("billing_month = :bm")
        params["bm"] = billing_month
    if credential_kind:
        clauses.append("credential_kind = :ck")
        params["ck"] = credential_kind
    if model:
        clauses.append("model = :model")
        params["model"] = model
    where = " AND ".join(clauses)

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        rows = session.execute(
            text(
                f"""
                SELECT id, tenant_id, user_id, trace_id, credential_kind, key_id,
                       model, provider, input_tokens, output_tokens, cost, currency,
                       billing_month, created_at
                FROM usage_records
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
                """
            ),
            params,
        ).fetchall()

    return [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "user_id": r.user_id,
            "trace_id": r.trace_id,
            "credential_kind": r.credential_kind,
            "key_id": r.key_id,
            "model": r.model,
            "provider": r.provider,
            "input_tokens": int(r.input_tokens),
            "output_tokens": int(r.output_tokens),
            "cost": float(r.cost),
            "currency": r.currency,
            "billing_month": r.billing_month,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/usage/export")
async def usage_export(
    tenant_id: str | None = Query(None),
    billing_month: str | None = Query(None),
    credential_kind: str | None = Query(None),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
):
    """CSV 导出（对账用）。"""
    if not _can_read_billing(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "BILLING_002", "message": "billing_export_denied"},
        )

    tid = _resolve_tenant_id(tenant, tenant_id)
    clauses = ["1=1"]
    params: dict[str, object] = {}
    if tid:
        clauses.append("tenant_id = :tid")
        params["tid"] = tid
    if billing_month:
        clauses.append("billing_month = :bm")
        params["bm"] = billing_month
    if credential_kind:
        clauses.append("credential_kind = :ck")
        params["ck"] = credential_kind
    where = " AND ".join(clauses)

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        rows = session.execute(
            text(
                f"""
                SELECT tenant_id, user_id, trace_id, credential_kind, key_id,
                       model, provider, input_tokens, output_tokens, cost, currency,
                       billing_month, created_at
                FROM usage_records
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT 10000
                """
            ),
            params,
        ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "tenant_id",
            "user_id",
            "trace_id",
            "credential_kind",
            "key_id",
            "model",
            "provider",
            "input_tokens",
            "output_tokens",
            "cost",
            "currency",
            "billing_month",
            "created_at",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.tenant_id,
                r.user_id,
                r.trace_id or "",
                r.credential_kind,
                r.key_id or "",
                r.model,
                r.provider,
                r.input_tokens,
                r.output_tokens,
                float(r.cost),
                r.currency,
                r.billing_month,
                r.created_at.isoformat() if r.created_at else "",
            ]
        )

    filename_tid = tid or "all"
    stamp = datetime.utcnow().strftime("%Y%m%d")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=usage_{filename_tid}_{stamp}.csv"
            )
        },
    )
