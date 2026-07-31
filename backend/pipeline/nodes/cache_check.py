"""缓存检查节点 — 精确缓存"""

from __future__ import annotations

import hashlib

from sqlalchemy import text

from backend.database.pgvector_session import get_pg_session
from backend.pipeline.state import PipelineState


async def cache_check(state: PipelineState) -> PipelineState:
    """检查缓存命中"""
    tenant_id = state["tenant_id"]
    user_id = state["user_id"]
    message = state["message"]

    query_hash = hashlib.sha256(message.encode()).hexdigest()[:16]
    exact_key = f"exact:{tenant_id}:{user_id}:{query_hash}"

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        exact = session.execute(
            text(
                "SELECT value FROM cache_entries "
                "WHERE cache_key = :key AND expires_at > now()"
            ),
            {"key": exact_key},
        ).fetchone()

        if exact:
            state["cache_hit"] = True
            state["cache_value"] = exact.value
            state["response"] = exact.value
            state["finish_reason"] = "cache_hit"
            return state

    return state


def should_skip_to_end(state: PipelineState) -> str:
    """条件边: 缓存命中 → END"""
    if state.get("cache_hit"):
        return "end"
    return "continue"
