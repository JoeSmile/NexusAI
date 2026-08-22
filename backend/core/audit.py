"""审计日志 — fire-and-forget BackgroundTasks + 血缘/NDJSON（Task 56 切片 5）。"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import text

from backend.core.audit_context import AuditLineage, get_audit_lineage
from backend.database.pgvector_session import get_pg_session

logger = logging.getLogger(__name__)


def log_audit(
    background_tasks: BackgroundTasks,
    tenant_id: str,
    user_id: str,
    action: str,
    trace_id: str,
    input_text: str = "",
    output_text: str = "",
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost: float = 0.0,
    latency_ms: float = 0.0,
    error_code: str | None = None,
    ip_address: str = "",
    user_agent: str = "",
    credential_kind: str | None = None,
    key_id: str | None = None,
    run_id: str | None = None,
    node_id: str | None = None,
    parent_trace_id: str | None = None,
    tool_use_id: str | None = None,
    decision_explain: str | None = None,
) -> None:
    """发起异步审计写入（不阻塞当前请求）"""
    lineage = get_audit_lineage()
    background_tasks.add_task(
        _write_audit,
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": action,
            "trace_id": trace_id,
            "input_text": input_text,
            "output_text": output_text,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
            "latency_ms": latency_ms,
            "error_code": error_code,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "credential_kind": credential_kind,
            "key_id": key_id,
            "run_id": run_id or lineage.run_id,
            "node_id": node_id or lineage.node_id,
            "parent_trace_id": parent_trace_id or lineage.parent_trace_id,
            "tool_use_id": tool_use_id or lineage.tool_use_id,
            "decision_explain": decision_explain,
            "created_at": datetime.utcnow(),
        },
    )


def write_audit_sync(record: dict) -> bool:
    """同步写入审计。成功或幂等命中返回 True；失败返回 False（不抛）。"""
    return _write_audit(record)


def write_governance_audit(
    *,
    tenant_id: str,
    user_id: str,
    capability_id: str,
    explain: dict[str, Any],
    lineage: AuditLineage | None = None,
    langfuse_ids: dict[str, str | None] | None = None,
) -> bool:
    """治理链 allow/deny 可解释审计（不含 params 明文）。"""
    lin = lineage or get_audit_lineage()
    payload = dict(explain)
    if langfuse_ids:
        payload["langfuse"] = {k: v for k, v in langfuse_ids.items() if v}
    detail = json.dumps(payload, ensure_ascii=False)
    tool_use_id = lin.tool_use_id or f"{capability_id}:{payload.get('idempotency_key') or 'invoke'}"
    trace_id = lin.trace_id or tool_use_id
    return write_audit_sync(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": "capability.governance",
            "trace_id": trace_id,
            "parent_trace_id": lin.parent_trace_id or lin.trace_id,
            "tool_use_id": tool_use_id,
            "input_text": capability_id[:200],
            "output_text": detail[:4000],
            "decision_explain": detail,
            "model": capability_id,
            "run_id": lin.run_id,
            "node_id": lin.node_id,
            "created_at": datetime.utcnow(),
        }
    )


def audit_row_to_ndjson_events(row: Any) -> list[dict[str, Any]]:
    """将 audit_logs 行映射为回放事件（turn_begin / tool_call / tool_result）。"""
    action = str(getattr(row, "action", "") or "")
    base = {
        "ts": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
        "tenant_id": getattr(row, "tenant_id", None),
        "user_id": getattr(row, "user_id", None),
        "trace_id": getattr(row, "trace_id", None),
        "parent_trace_id": getattr(row, "parent_trace_id", None),
        "tool_use_id": getattr(row, "tool_use_id", None),
        "audit_id": getattr(row, "id", None),
    }
    if action == "chat":
        return [
            {
                **base,
                "type": "turn_begin",
                "input_preview": (getattr(row, "input_text", "") or "")[:500],
            }
        ]
    if action in {"capability.governance", "chat.task_plan"}:
        explain_raw = getattr(row, "decision_explain", None) or getattr(row, "output_text", "")
        explain: dict[str, Any] | None = None
        if explain_raw:
            try:
                explain = json.loads(str(explain_raw))
            except json.JSONDecodeError:
                explain = {"raw": str(explain_raw)[:1000]}
        return [
            {
                **base,
                "type": "tool_call",
                "action": action,
                "capability_id": getattr(row, "model", None) or getattr(row, "input_text", ""),
                "decision_explain": explain,
            }
        ]
    if action == "capability.invoke":
        return [
            {
                **base,
                "type": "tool_result",
                "ok": not getattr(row, "error_code", None),
                "error_code": getattr(row, "error_code", None),
                "output_preview": (getattr(row, "output_text", "") or "")[:500],
                "latency_ms": getattr(row, "latency_ms", None),
                "cost": getattr(row, "cost", None),
            }
        ]
    return [
        {
            **base,
            "type": "audit_event",
            "action": action,
            "error_code": getattr(row, "error_code", None),
        }
    ]


def ndjson_lines_from_rows(rows: list[Any]) -> Iterator[str]:
    """按时间正序输出 NDJSON 行（审计回放）。"""
    ordered = sorted(
        rows,
        key=lambda r: (
            getattr(r, "created_at", None) or datetime.min,
            int(getattr(r, "id", 0) or 0),
        ),
    )
    for row in ordered:
        for event in audit_row_to_ndjson_events(row):
            yield json.dumps(event, ensure_ascii=False) + "\n"


def _write_audit(record: dict) -> bool:
    """写入 audit_logs 表（供 BackgroundTasks 或 sync 调用）。"""
    try:
        record = {
            "credential_kind": None,
            "key_id": None,
            "run_id": None,
            "node_id": None,
            "dedupe_key": None,
            "parent_trace_id": None,
            "tool_use_id": None,
            "decision_explain": None,
            "model": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
            "latency_ms": 0.0,
            "error_code": None,
            "ip_address": "",
            "user_agent": "",
            "input_text": "",
            "output_text": "",
            "trace_id": "",
            "created_at": datetime.utcnow(),
            **record,
        }
        dedupe_key = record.get("dedupe_key") or None
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            if dedupe_key:
                hit = session.execute(
                    text(
                        """
                        SELECT 1 FROM audit_logs
                        WHERE tenant_id = :tid AND dedupe_key = :dk
                        LIMIT 1
                        """
                    ),
                    {"tid": record["tenant_id"], "dk": dedupe_key},
                ).fetchone()
                if hit:
                    return True
            sql = text("""
                INSERT INTO audit_logs
                    (tenant_id, user_id, action, trace_id,
                     input_text, output_text, model,
                     input_tokens, output_tokens, cost, latency_ms,
                     error_code, ip_address, user_agent,
                     credential_kind, key_id, run_id, node_id,
                     dedupe_key, parent_trace_id, tool_use_id, decision_explain,
                     created_at)
                VALUES
                    (:tenant_id, :user_id, :action, :trace_id,
                     :input_text, :output_text, :model,
                     :input_tokens, :output_tokens, :cost, :latency_ms,
                     :error_code, :ip_address, :user_agent,
                     :credential_kind, :key_id, :run_id, :node_id,
                     :dedupe_key, :parent_trace_id, :tool_use_id, :decision_explain,
                     :created_at)
            """)
            session.execute(sql, record)
            session.commit()
        return True
    except Exception:
        logger.exception("审计日志写入失败")
        return False
