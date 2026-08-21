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
    credential_kind: str | None = None,
    key_id: str | None = None,
    run_id: str | None = None,
    node_id: str | None = None,
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
            "credential_kind": credential_kind,
            "key_id": key_id,
            "run_id": run_id,
            "node_id": node_id,
            "created_at": datetime.utcnow(),
        },
    )


def write_audit_sync(record: dict) -> bool:
    """同步写入审计。成功或幂等命中返回 True；失败返回 False（不抛）。"""
    return _write_audit(record)


def _write_audit(record: dict) -> bool:
    """写入 audit_logs 表（供 BackgroundTasks 或 sync 调用）。"""
    try:
        # Defaults so callers that omit Wave A fields still work
        record = {
            "credential_kind": None,
            "key_id": None,
            "run_id": None,
            "node_id": None,
            "dedupe_key": None,
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
        # I-1(评审 08-15)：去重键——重复投递/重放撞唯一约束 → 静默跳过（幂等）
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
                     dedupe_key, created_at)
                VALUES
                    (:tenant_id, :user_id, :action, :trace_id,
                     :input_text, :output_text, :model,
                     :input_tokens, :output_tokens, :cost, :latency_ms,
                     :error_code, :ip_address, :user_agent,
                     :credential_kind, :key_id, :run_id, :node_id,
                     :dedupe_key, :created_at)
            """)
            session.execute(sql, record)
            session.commit()
        return True
    except Exception:
        logger.exception("审计日志写入失败")
        return False
