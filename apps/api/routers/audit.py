"""审计日志查询 + 导出（Wave B4: OrgScope 过滤）"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from packages.audit_org_scope import audit_user_filter
from packages.database.pgvector_session import get_pg_session
from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext

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


def _can_decrypt_audit_text(tenant: TenantContext) -> bool:
    return tenant.role in ("auditor", "super_admin")


def _resolve_row_texts(row: object, tenant: TenantContext) -> tuple[str, str]:
    from packages.security.audit_crypto import resolve_audit_text

    return resolve_audit_text(row, can_decrypt=_can_decrypt_audit_text(tenant))


@router.get("/logs")
async def query_audit_logs(
    tenant_id: str | None = Query(None, description="按租户筛选"),
    start: str | None = Query(None, description="开始时间 ISO"),
    end: str | None = Query(None, description="结束时间 ISO"),
    action: str | None = Query(None, description="按操作筛选"),
    trace_id: str | None = Query(None, description="按 trace_id 筛选（Task 63）"),
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
    if trace_id:
        conditions.append("trace_id = :trace_id")
        params["trace_id"] = trace_id.strip()

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


@router.get("/usage-summary")
async def usage_summary(
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
):
    """今日用量（audit_logs 中 action=chat 的聚合；经 OrgScope 收窄）。不返回对话正文。"""
    from fastapi import HTTPException

    if not _can_query_audit(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "AUDIT_001", "message": "audit_read_denied"},
        )

    from datetime import UTC, datetime

    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    tid = tenant.tenant_id
    session_factory = get_pg_session()
    conditions = ["tenant_id = :tid", "created_at >= :start", "action = :chat_action"]
    params: dict = {"tid": tid, "start": start.isoformat(), "chat_action": "chat"}

    daily_limit = 10.0
    with session_factory.Session() as session:
        frag, extra = audit_user_filter(session, tenant)
        if frag:
            conditions.append(frag)
            params.update(extra)
        row = session.execute(
            text(
                f"""
                SELECT COUNT(*) AS calls,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(cost), 0) AS cost
                FROM audit_logs
                WHERE {' AND '.join(conditions)}
                """
            ),
            params,
        ).fetchone()
        cfg = session.execute(
            text("SELECT config FROM tenant_config WHERE tenant_id = :tid"),
            {"tid": tid},
        ).fetchone()
        if cfg and isinstance(cfg.config, dict):
            daily_limit = float(
                (cfg.config.get("budget") or {}).get("daily_limit") or daily_limit
            )

    calls = int(row.calls or 0) if row else 0
    inp = int(row.input_tokens or 0) if row else 0
    out = int(row.output_tokens or 0) if row else 0
    cost = float(row.cost or 0.0) if row else 0.0
    return {
        "period": "today_utc",
        "calls": calls,
        "input_tokens": inp,
        "output_tokens": out,
        "tokens": inp + out,
        "cost": cost,
        "daily_limit": daily_limit,
    }


@router.get("/trace/{trace_id}/events")
async def trace_replay_events(
    trace_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
):
    """单 trace 回放事件（audit:read；脱敏预览；不需 export 权限 — Task 63 拍板 1A）。"""
    from fastapi import HTTPException

    from packages.audit import build_trace_replay_events

    if not _can_query_audit(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "AUDIT_001", "message": "audit_read_denied"},
        )

    tid = trace_id.strip()
    if not tid:
        raise HTTPException(
            status_code=400,
            detail={"code": "AUDIT_003", "message": "trace_id_required"},
        )

    session_factory = get_pg_session()
    conditions = ["trace_id = :trace_id"]
    params: dict = {"trace_id": tid}
    if not tenant.is_cross_tenant:
        conditions.append("tenant_id = :tid")
        params["tid"] = tenant.tenant_id

    with session_factory.Session() as session:
        frag, extra = audit_user_filter(session, tenant)
        if frag:
            conditions.append(frag)
            params.update(extra)
        sql = text(f"""
            SELECT id, tenant_id, user_id, action, trace_id,
                   parent_trace_id, tool_use_id, decision_explain,
                   input_text, output_text, input_text_enc, output_text_enc,
                   text_enc_version, model,
                   input_tokens, output_tokens, cost, latency_ms,
                   error_code, ip_address, user_agent, created_at
            FROM audit_logs
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at ASC
            LIMIT 500
        """)
        rows = session.execute(sql, params).fetchall()

    events = build_trace_replay_events(
        list(rows),
        resolve_row_texts=lambda row: _resolve_row_texts(row, tenant),
    )
    return {"trace_id": tid, "events": events, "count": len(events)}


@router.get("/export")
async def export_audit(
    tenant_id: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    action: str | None = Query(None, description="按操作筛选"),
    trace_id: str | None = Query(None, description="按 trace_id 筛选（Task 63）"),
    format: str = Query("csv", description="csv | ndjson"),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
):
    """导出审计日志：默认 CSV；format=ndjson 为回放事件流（Task 56）。"""
    from fastapi import HTTPException

    from packages.audit import ndjson_lines_from_rows

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
    if trace_id:
        conditions.append("trace_id = :trace_id")
        params["trace_id"] = trace_id.strip()

    with session_factory.Session() as session:
        frag, extra = audit_user_filter(session, tenant)
        if frag:
            conditions.append(frag)
            params.update(extra)
        sql = text(f"""
            SELECT id, tenant_id, user_id, action, trace_id,
                   parent_trace_id, tool_use_id, decision_explain,
                   input_text, output_text, input_text_enc, output_text_enc,
                   text_enc_version, model,
                   input_tokens, output_tokens, cost, latency_ms,
                   error_code, ip_address, user_agent, created_at
            FROM audit_logs
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at ASC
            LIMIT 10000
        """)
        rows = session.execute(sql, params).fetchall()

    fmt = (format or "csv").strip().lower()
    if fmt == "ndjson":
        from types import SimpleNamespace

        resolved_rows = []
        for row in rows:
            inp, out = _resolve_row_texts(row, tenant)
            mapping = dict(row._mapping) if hasattr(row, "_mapping") else row._asdict()
            mapping["input_text"] = inp
            mapping["output_text"] = out
            resolved_rows.append(SimpleNamespace(**mapping))
        body = "".join(ndjson_lines_from_rows(resolved_rows))
        filename_tid = tid or "all"
        return StreamingResponse(
            iter([body]),
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=audit_{filename_tid}_"
                    f"{datetime.now().strftime('%Y%m%d')}.ndjson"
                )
            },
        )

    return _export_audit_csv(rows, tid, tenant)


def _export_audit_csv(rows, tid: str | None, tenant: TenantContext) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "tenant_id",
        "user_id",
        "action",
        "trace_id",
        "parent_trace_id",
        "tool_use_id",
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
        inp, out = _resolve_row_texts(r, tenant)
        writer.writerow([
            r.id,
            r.tenant_id,
            r.user_id,
            r.action,
            r.trace_id,
            getattr(r, "parent_trace_id", None),
            getattr(r, "tool_use_id", None),
            inp[:500],
            out[:500],
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
