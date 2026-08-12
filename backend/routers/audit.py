"""审计日志查询 + 导出（Wave B4: OrgScope 过滤）"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from backend.core.audit_org_scope import audit_user_filter
from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.auth.models import TenantContext
from backend.database.pgvector_session import get_pg_session

router = APIRouter(prefix="/audit", tags=["audit"])


def _can_query_audit(tenant: TenantContext) -> bool:
    """Auditor/admin full; others may see narrowed own/dept slice."""
    if tenant.has_permission("audit:read") or tenant.has_permission("admin:*"):
        return True
    # tenant_admin / dept_manager / member — narrowed by OrgScope
    return tenant.role in (
        "tenant_admin",
        "user",
        "auditor",
        "super_admin",
    )


def _can_export_audit(tenant: TenantContext) -> bool:
    if tenant.has_permission("audit:export") or tenant.has_permission("admin:*"):
        return True
    return tenant.role in ("tenant_admin", "auditor", "super_admin")


@router.get("/logs")
async def query_audit_logs(
    tenant_id: str | None = Query(None, description="按租户筛选"),
    start: str | None = Query(None, description="开始时间 ISO"),
    end: str | None = Query(None, description="结束时间 ISO"),
    action: str | None = Query(None, description="按操作筛选"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
):
    """查询审计日志（经 OrgScope 收窄）"""
    from fastapi import HTTPException

    if not _can_query_audit(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "AUDIT_001", "message": "audit_read_denied"},
        )

    session_factory = get_pg_session()
    tid = tenant_id if tenant.is_cross_tenant else tenant.tenant_id

    conditions = ["1=1"]
    params: dict = {"lim": limit, "off": offset}
    if tid:
        conditions.append("tenant_id = :tid")
        params["tid"] = tid
    if start:
        conditions.append("created_at >= :start")
        params["start"] = start
    if end:
        conditions.append("created_at <= :end")
        params["end"] = end
    if action:
        conditions.append("action = :action")
        params["action"] = action

    with session_factory.Session() as session:
        frag, extra = audit_user_filter(session, tenant)
        if frag:
            conditions.append(frag)
            params.update(extra)
        sql = text(f"""
            SELECT id, tenant_id, user_id, action, trace_id,
                   model, input_tokens, output_tokens, cost,
                   latency_ms, error_code, ip_address, created_at
            FROM audit_logs
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            LIMIT :lim OFFSET :off
        """)
        rows = session.execute(sql, params).fetchall()

    return [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "user_id": r.user_id,
            "action": r.action,
            "trace_id": r.trace_id,
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost": r.cost,
            "latency_ms": r.latency_ms,
            "error_code": r.error_code,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/export")
async def export_audit_csv(
    tenant_id: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    action: str | None = Query(None, description="按操作筛选"),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
):
    """导出审计日志为 CSV（经 OrgScope 收窄；普通 member 不可导出）"""
    from fastapi import HTTPException

    if not _can_export_audit(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "AUDIT_002", "message": "audit_export_denied"},
        )

    tid = tenant_id if tenant.is_cross_tenant else tenant.tenant_id
    session_factory = get_pg_session()

    conditions = ["1=1"]
    params: dict = {}
    if tid:
        conditions.append("tenant_id = :tid")
        params["tid"] = tid
    if start:
        conditions.append("created_at >= :start")
        params["start"] = start
    if end:
        conditions.append("created_at <= :end")
        params["end"] = end
    if action:
        conditions.append("action = :action")
        params["action"] = action

    with session_factory.Session() as session:
        frag, extra = audit_user_filter(session, tenant)
        if frag:
            conditions.append(frag)
            params.update(extra)
        sql = text(f"""
            SELECT id, tenant_id, user_id, action, trace_id,
                   input_text, output_text, model,
                   input_tokens, output_tokens, cost, latency_ms,
                   error_code, ip_address, user_agent, created_at
            FROM audit_logs
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            LIMIT 10000
        """)
        rows = session.execute(sql, params).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "tenant_id",
        "user_id",
        "action",
        "trace_id",
        "input_text",
        "output_text",
        "model",
        "input_tokens",
        "output_tokens",
        "cost",
        "latency_ms",
        "error_code",
        "ip_address",
        "user_agent",
        "created_at",
    ])
    for r in rows:
        writer.writerow([
            r.id,
            r.tenant_id,
            r.user_id,
            r.action,
            r.trace_id,
            (r.input_text or "")[:500],
            (r.output_text or "")[:500],
            r.model,
            r.input_tokens,
            r.output_tokens,
            r.cost,
            r.latency_ms,
            r.error_code,
            r.ip_address,
            r.user_agent,
            r.created_at.isoformat() if r.created_at else "",
        ])

    output.seek(0)
    filename_tid = tid or "all"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=audit_{filename_tid}_"
                f"{datetime.now().strftime('%Y%m%d')}.csv"
            )
        },
    )
