"""深度健康检查 — 数据库 / pgvector / LLM / LangFuse（LangFuse 外呼不走本路径）"""

from __future__ import annotations

import time
import urllib.error
import urllib.request

from fastapi import APIRouter
from sqlalchemy import text
from starlette.responses import JSONResponse

from packages.database.pgvector_session import get_pg_session

router = APIRouter(tags=["system"])


def langfuse_local_status() -> dict:
    """进程内开关/SDK 状态，无出站 HTTP。供 GET /health 使用。"""
    from packages.observability.langfuse_client import (  # type: ignore
        _base_url,
        get_langfuse,
        langfuse_enabled,
    )

    if not langfuse_enabled():
        return {"status": "disabled"}
    if get_langfuse() is None:
        return {"status": "not_configured"}
    return {"status": "configured", "host": _base_url()}


def langfuse_status() -> dict:
    """可选远端探测。不要挂在同步 /health 上（urlopen 最多 2s）。"""
    local = langfuse_local_status()
    if local.get("status") != "configured":
        return local
    host = local.get("host") or ""
    try:
        req = urllib.request.Request(f"{host}/api/public/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            ok = 200 <= getattr(resp, "status", 200) < 300
        return {"status": "up" if ok else "down", "host": host}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"status": "down", "host": host}


@router.get("/health")
async def health_check():
    """深度健康检查"""
    checks: dict = {}
    overall = "healthy"

    # 1. 数据库
    try:
        t0 = time.time()
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            session.execute(text("SELECT 1"))
        db_latency = (time.time() - t0) * 1000
        checks["database"] = {"status": "up", "latency_ms": round(db_latency, 1)}
    except Exception as e:
        checks["database"] = {"status": "down", "error": str(e)}
        overall = "degraded"

    # 2. pgvector 扩展
    try:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            row = session.execute(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            ).fetchone()
        checks["pgvector"] = {
            "status": "up" if row else "missing",
            "version": row[0] if row else None,
        }
        if not row:
            overall = "degraded"
    except Exception as e:
        checks["pgvector"] = {"status": "down", "error": str(e)}
        overall = "degraded"

    # 3. LLM API（可选 — Batch 8 前可能无 KeyRepository）
    try:
        from packages.key_repository import LLMKeyRepository  # type: ignore

        repo = LLMKeyRepository()
        key = await repo.get_key("default", "default")
        checks["llm_api"] = {"status": "up" if key else "no_key_configured"}
    except Exception:
        checks["llm_api"] = {"status": "unknown"}

    # 4. 缓存表
    try:
        from packages.database.pgvector_session import CacheEntry

        session_factory = get_pg_session()
        with session_factory.Session() as session:
            count = session.query(CacheEntry).count()
        checks["cache"] = {"status": "up", "entries": count}
    except Exception:
        checks["cache"] = {"status": "down"}

    # 5. LangFuse（可选；仅本地 SDK 状态，不出站）
    try:
        checks["langfuse"] = langfuse_local_status()
    except Exception:
        checks["langfuse"] = {"status": "not_configured"}

    # 6. 审计写入失败计数（Task 59 S3）
    try:
        from packages.audit import audit_circuit_open, audit_write_failure_count

        failures = audit_write_failure_count()
        checks["audit"] = {
            "write_failures": failures,
            "circuit": "open" if audit_circuit_open() else "closed",
        }
    except Exception:
        checks["audit"] = {"write_failures": None, "status": "unknown"}

    # 7. 意图 BERT（缺权重不 503：规则兜底仍可用）
    try:
        from packages.intent.routers.intent_router import intent_runtime_status

        checks["intent_model"] = intent_runtime_status()
    except Exception:
        checks["intent_model"] = {"status": "unknown"}

    http_status = 200 if overall == "healthy" else 503
    return JSONResponse(
        status_code=http_status,
        content={
            "status": overall,
            "checks": checks,
        },
    )
