"""深度健康检查 — 数据库 / pgvector / LLM / LangFuse"""

from __future__ import annotations

import time

from fastapi import APIRouter
from sqlalchemy import text
from starlette.responses import JSONResponse

from backend.database.pgvector_session import get_pg_session

router = APIRouter(tags=["system"])


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
        from backend.core.key_repository import LLMKeyRepository  # type: ignore

        repo = LLMKeyRepository()
        key = await repo.get_key("default", "default")
        checks["llm_api"] = {"status": "up" if key else "no_key_configured"}
    except Exception:
        checks["llm_api"] = {"status": "unknown"}

    # 4. 缓存表
    try:
        from backend.database.pgvector_session import CacheEntry

        session_factory = get_pg_session()
        with session_factory.Session() as session:
            count = session.query(CacheEntry).count()
        checks["cache"] = {"status": "up", "entries": count}
    except Exception:
        checks["cache"] = {"status": "down"}

    # 5. LangFuse（可选）
    try:
        from backend.observability.langfuse_client import get_langfuse  # type: ignore

        get_langfuse()
        checks["langfuse"] = {"status": "configured"}
    except Exception:
        checks["langfuse"] = {"status": "not_configured"}

    http_status = 200 if overall == "healthy" else 503
    return JSONResponse(
        status_code=http_status,
        content={
            "status": overall,
            "checks": checks,
        },
    )
