"""Chat 语义缓存 — Task 72 切片 4（默认 OFF）。

lookup 在 ``model_router``（已选 model + intent + context_hash，D4）；
``cache_check`` 仅 exact/fingerprint（此时尚无完整上下文）。
"""

from __future__ import annotations

import json
import logging
import math
import os
import time

from backend.core.text_normalize import make_normalized_query_hash, normalize_text
from backend.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

_SCOPE_PREFIX = "sem"
_DEFAULT_TTL = 3600


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def semantic_cache_enabled() -> bool:
    return _env_bool("SEMANTIC_CACHE_ENABLED", False)


def similarity_threshold() -> float:
    try:
        return float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.93") or "0.93")
    except ValueError:
        return 0.93


def ttl_seconds() -> int:
    try:
        return int(os.getenv("SEMANTIC_CACHE_TTL", str(_DEFAULT_TTL)) or _DEFAULT_TTL)
    except ValueError:
        return _DEFAULT_TTL


def prompt_version(state: PipelineState) -> str:
    return str(state.get("ab_variant") or os.getenv("CHAT_PROMPT_VERSION") or "1")


def compute_context_hash(state: PipelineState) -> str:
    """记忆 + 检索上下文哈希；无上下文时 ``\"-\"``（D4）。"""
    memory_block = (state.get("memory_prompt_block") or "").strip()
    rag_ids = sorted(str(x) for x in (state.get("rag_retrieved_ids") or []))
    warm = state.get("warm_memory") or {}
    if not memory_block and not rag_ids and not warm:
        return "-"
    blob = "|".join(
        [
            memory_block,
            ",".join(rag_ids),
            json.dumps(warm, sort_keys=True, ensure_ascii=False),
        ]
    )
    return make_normalized_query_hash(blob)


def scope_key(
    *,
    tenant_id: str,
    model: str,
    prompt_version: str,
    intent: str,
    context_hash: str,
) -> str:
    return (
        f"{tenant_id}:{model}:{prompt_version}:{intent or '-'}:{context_hash or '-'}"
    )


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _redis():
    from backend.core.redis_tools import get_sync_redis

    return get_sync_redis(decode_responses=True)


def _entry_key(scope: str, entry_id: str) -> str:
    return f"{_SCOPE_PREFIX}:e:{scope}:{entry_id}"


def _idx_key(scope: str) -> str:
    return f"{_SCOPE_PREFIX}:idx:{scope}"


def lookup(state: PipelineState) -> str | None:
    """近邻查找；redis / embed 失败静默 miss。"""
    if not semantic_cache_enabled():
        return None
    if state.get("cache_bypass") or state.get("cache_hit"):
        return None

    tenant_id = state["tenant_id"]
    model = (state.get("selected_model") or "").strip()
    if not model:
        return None

    query = normalize_text(state.get("message") or "")
    if not query:
        return None

    intent = (state.get("intent") or "-").strip() or "-"
    ctx = compute_context_hash(state)
    pv = prompt_version(state)
    scope = scope_key(
        tenant_id=tenant_id,
        model=model,
        prompt_version=pv,
        intent=intent,
        context_hash=ctx,
    )

    r = _redis()
    if r is None:
        logger.debug("semantic_cache: redis unavailable; miss")
        return None

    try:
        from backend.database.embeddings import embed_text

        qvec = embed_text(query, tenant_id=tenant_id)
    except Exception:
        logger.debug("semantic_cache: embed failed; miss", exc_info=True)
        return None

    theta = similarity_threshold()
    best_sim = 0.0
    best_response: str | None = None
    now = time.time()

    try:
        members = r.smembers(_idx_key(scope)) or set()
        for raw_id in members:
            entry_id = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
            payload_raw = r.get(_entry_key(scope, entry_id))
            if not payload_raw:
                continue
            payload = json.loads(payload_raw)
            expires_at = float(payload.get("expires_at") or 0)
            if expires_at and expires_at < now:
                continue
            vec = payload.get("vec") or []
            sim = _cosine(qvec, vec)
            if sim > best_sim:
                best_sim = sim
                best_response = str(payload.get("response") or "")
    except Exception:
        logger.debug("semantic_cache: lookup failed; miss", exc_info=True)
        return None

    if best_sim >= theta and best_response:
        logger.info(
            "semantic_cache hit tenant=%s model=%s sim=%.3f",
            tenant_id,
            model,
            best_sim,
        )
        return best_response
    return None


def upsert(state: PipelineState, response: str) -> None:
    """异步写路径入口；失败静默。"""
    if not semantic_cache_enabled():
        return
    if state.get("cache_bypass"):
        return
    if not (response or "").strip():
        return
    if state.get("finish_reason") in ("semantic_cache_hit", "cache_hit"):
        return

    tenant_id = state["tenant_id"]
    model = (state.get("selected_model") or "").strip()
    if not model:
        return

    query = normalize_text(state.get("message") or "")
    if not query:
        return

    intent = (state.get("intent") or "-").strip() or "-"
    ctx = compute_context_hash(state)
    pv = prompt_version(state)
    scope = scope_key(
        tenant_id=tenant_id,
        model=model,
        prompt_version=pv,
        intent=intent,
        context_hash=ctx,
    )
    entry_id = make_normalized_query_hash(query)

    r = _redis()
    if r is None:
        return

    try:
        from backend.database.embeddings import embed_text

        vec = embed_text(query, tenant_id=tenant_id)
        ttl = ttl_seconds()
        payload = json.dumps(
            {
                "vec": vec,
                "response": response,
                "expires_at": time.time() + ttl,
            },
            ensure_ascii=False,
        )
        r.set(_entry_key(scope, entry_id), payload, ex=ttl)
        r.sadd(_idx_key(scope), entry_id)
        r.expire(_idx_key(scope), ttl)
    except Exception:
        logger.debug("semantic_cache: upsert failed", exc_info=True)


def try_apply_semantic_cache(state: PipelineState) -> bool:
    """命中则写入 state 并返回 True。"""
    hit = lookup(state)
    if not hit:
        return False
    state["cache_hit"] = True
    state["cache_value"] = hit
    state["response"] = hit
    state["finish_reason"] = "semantic_cache_hit"
    try:
        from backend.core.metrics import cache_hits

        cache_hits.labels(tenant=state["tenant_id"], cache_type="semantic").inc()
    except Exception:
        pass
    return True


def reset_semantic_cache_for_tests() -> None:
    """测试用：清 redis 惰性连接。"""
    from backend.core.redis_tools import reset_redis_clients_for_tests

    reset_redis_clients_for_tests()
