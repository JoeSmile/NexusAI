"""审计日志查询 + 导出"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_any_permission
from backend.database.pgvector_session import get_pg_session

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs")
async def query_audit_logs(
    tenant_id: str | None = Query(None, description="按租户筛选"),
    start: str | None = Query(None, description="开始时间 ISO"),
    end: str | None = Query(None, description="结束时间 ISO"),
    action: str | None = Query(None, description="按操作筛选"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    tenant: TenantContext = Depends(
        require_any_permission(["audit:read", "admin:*"])
    ),
):
    """查询审计日志"""
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

    sql = text(f"""
        SELECT id, tenant_id, user_id, action, trace_id,
               model, input_tokens, output_tokens, cost,
               latency_ms, error_code, ip_address, created_at
        FROM audit_logs
        WHERE {' AND '.join(conditions)}
        ORDER BY created_at DESC
        LIMIT :lim OFFSET :off
    """)

    with session_factory.Session() as session:
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
    tenant: TenantContext = Depends(
        require_any_permission(["audit:export", "admin:*"])
    ),
):
    """导出审计日志为 CSV"""
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

    with session_factory.Session() as session:
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
