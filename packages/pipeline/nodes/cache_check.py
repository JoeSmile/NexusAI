"""缓存检查节点 — 精确 + 指纹缓存"""

from __future__ import annotations

import logging

from sqlalchemy import text

from packages.text_normalize import make_normalized_query_hash
from backend.database.pgvector_session import get_pg_session
from packages.observability.decorators import observe
from packages.pipeline.state import PipelineState

logger = logging.getLogger(__name__)


def make_query_hash(message: str) -> str:
    """生成查询哈希（前 16 位）— 与 preprocess / RAG 同源 normalize。"""
    return make_normalized_query_hash(message)


def _cheap_fingerprint(message: str) -> str | None:
    """廉价意图指纹预检 — 仅通用意图启发式（greeting）；不做业务域模板匹配。"""
    from packages.pipeline.cache.fingerprint_cache import make_fingerprint

    greetings = ["你好", "嗨", "hello", "hi", "早上好", "晚上好"]

    if any(g in message for g in greetings):
        return make_fingerprint("greeting", {})
    return None


@observe(name="pipeline.cache_check")
async def cache_check(state: PipelineState) -> PipelineState:
    """检查精确缓存 + 指纹缓存；exact key 只用 state.query_hash（Task 39）。"""
    tenant_id = state["tenant_id"]
    user_id = state["user_id"]
    message = state["message"]

    if state.get("cache_bypass"):
        logger.info(
            "cache_check: cache_bypass (tenant=%s); skip read",
            tenant_id,
        )
        from packages.metrics import cache_misses

        cache_misses.labels(tenant=tenant_id, cache_type="bypass").inc()
        return state

    query_hash = state.get("query_hash") or ""
    if not query_hash:
        logger.warning(
            "cache_check: missing query_hash (tenant=%s); treating as miss",
            tenant_id,
        )
        from packages.metrics import cache_misses

        cache_misses.labels(tenant=tenant_id, cache_type="pipeline").inc()
        return state

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        exact_key = f"exact:{tenant_id}:{user_id}:{query_hash}"
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
            from packages.metrics import cache_hits

            cache_hits.labels(tenant=tenant_id, cache_type="exact").inc()
            return state

        # fingerprint 在 analyze 之后才完整；此处用廉价意图启发式预检模板缓存
        fingerprint = state.get("fingerprint") or _cheap_fingerprint(message)
        if fingerprint:
            state["fingerprint"] = fingerprint
            template_key = f"template:{tenant_id}:{fingerprint}"
            template = session.execute(
                text(
                    "SELECT value FROM cache_entries "
                    "WHERE cache_key = :key AND expires_at > now()"
                ),
                {"key": template_key},
            ).fetchone()
            if template:
                state["cache_hit"] = True
                state["cache_value"] = template.value
                state["response"] = template.value
                state["finish_reason"] = "cache_hit"
                from packages.metrics import cache_hits

                cache_hits.labels(tenant=tenant_id, cache_type="template").inc()
                return state

    # Task 72：语义缓存在 model_router（D4：需 model + intent + context_hash）。

    from packages.metrics import cache_misses

    cache_misses.labels(tenant=tenant_id, cache_type="pipeline").inc()
    return state


def should_skip_to_end(state: PipelineState) -> str:
    return "end" if state.get("cache_hit") else "continue"
