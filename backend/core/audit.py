"""审计日志 — fire-and-forget BackgroundTasks"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import BackgroundTasks
from sqlalchemy import text

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
) -> None:
    """发起异步审计写入（不阻塞当前请求）"""
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
            "created_at": datetime.utcnow(),
        },
    )


def write_audit_sync(record: dict) -> None:
    """同步写入审计（不需要 BackgroundTasks 时用）"""
    _write_audit(record)


def _write_audit(record: dict) -> None:
    """写入 audit_logs 表（供 BackgroundTasks 或 sync 调用）"""
    try:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            sql = text("""
                INSERT INTO audit_logs
                    (tenant_id, user_id, action, trace_id,
                     input_text, output_text, model,
                     input_tokens, output_tokens, cost, latency_ms,
                     error_code, ip_address, user_agent, created_at)
                VALUES
                    (:tenant_id, :user_id, :action, :trace_id,
                     :input_text, :output_text, :model,
                     :input_tokens, :output_tokens, :cost, :latency_ms,
                     :error_code, :ip_address, :user_agent, :created_at)
            """)
            session.execute(sql, record)
            session.commit()
    except Exception:
        logger.exception("审计日志写入失败")
