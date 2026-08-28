"""世界域 key 选择器 — Task 41 Slice 2 / S2a（P0-1 / P0-2）。

语义检索只做 key 选择；渲染仍走 assemble 按前缀格式化器。
mode=semantic miss / hash embedding 兜底 → 退回 keyword（平滑替换，不两套并存）。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

logger = logging.getLogger(__name__)

RetrievalMode = Literal["keyword", "semantic"]

# 世界域按需召回（todo 常驻高优先级，不经本选择器过滤）
WORLD_PREFIXES: tuple[str, ...] = ("entity:", "decision:", "error:")

_DEFAULT_SMALL_WORLD_THRESHOLD = 20


def _small_world_threshold() -> int:
    raw = (os.getenv("MEMORY_SMALL_WORLD_THRESHOLD") or "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return _DEFAULT_SMALL_WORLD_THRESHOLD

# 按域相似度阈值（env 可调；P1 写死默认）
_DOMAIN_MIN_SCORE: dict[str, float] = {
    "entity": 0.55,
    "decision": 0.7,
    "error": 0.85,
}


def _domain_of(key: str) -> str:
    return key.split(":", 1)[0] if ":" in key else ""


def _min_score_for(key: str) -> float:
    domain = _domain_of(key)
    env_key = f"MEMORY_SEMANTIC_MIN_{domain.upper()}"
    raw = os.getenv(env_key)
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return float(_DOMAIN_MIN_SCORE.get(domain, 0.3))


def _keyword_hit(query_text: str, key: str, val: str) -> bool:
    """原 assemble ``_hit`` 2-gram 逻辑（降级回退用）。"""
    q = (query_text or "").strip().lower()
    if not q:
        return False
    blob = f"{key} {val}".lower()
    for i in range(len(q) - 1):
        tok = q[i : i + 2]
        if tok in blob:
            return True
    return key.split(":", 1)[-1].lower() in q


def keyword_select(query: str, items: dict[str, str]) -> list[str]:
    """关键词召回：返回命中的世界域 key 列表（保插入序）。"""
    out: list[str] = []
    for key, val in items.items():
        if not key.startswith(WORLD_PREFIXES):
            continue
        if key.startswith("pending:"):
            continue
        if _keyword_hit(query, key, str(val)):
            out.append(key)
    return out


def select_world_items(
    query: str,
    items: dict[str, str],
    mode: RetrievalMode = "keyword",
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    limit: int = 20,
) -> list[str]:
    """选择应注入的世界域 keys。

    - ``keyword``: 2-gram / slug 子串
    - ``semantic``: ``search_user_memories`` + 域阈值；hash fallback 或 miss → keyword
    """
    world = {
        k: v
        for k, v in (items or {}).items()
        if k.startswith(WORLD_PREFIXES) and not k.startswith("pending:")
    }
    if not query or not query.strip():
        return list(world.keys())

    if mode != "semantic":
        return keyword_select(query, world)

    # Task 51: 小世界全量注入，跳过 embedding API
    if len(world) <= _small_world_threshold():
        logger.debug(
            "memory_retrieval_mode=full reason=small_world n=%d",
            len(world),
        )
        return list(world.keys())

    try:
        from backend.database.embeddings import embedding_uses_hash_fallback
    except Exception:
        embedding_uses_hash_fallback = lambda: True  # noqa: E731

    if embedding_uses_hash_fallback():
        logger.info("memory_retrieval_mode=keyword reason=embedding_hash_fallback")
        return keyword_select(query, world)

    if not tenant_id or not user_id:
        logger.info("memory_retrieval_mode=keyword reason=missing_tenant_or_user")
        return keyword_select(query, world)

    try:
        from backend.database.vector_ops import search_user_memories

        hits = search_user_memories(
            tenant_id,
            user_id,
            query,
            limit=limit,
            min_score=0.3,
            domains=["entity", "decision", "error"],
        )
    except Exception:
        logger.warning("semantic search failed; keyword fallback", exc_info=True)
        return keyword_select(query, world)

    selected: list[str] = []
    for h in hits:
        key = str(h.get("key") or "")
        if key not in world:
            continue
        sim = float(h.get("similarity") or 0.0)
        if sim < _min_score_for(key):
            continue
        selected.append(key)

    if selected:
        logger.debug(
            "memory_retrieval_mode=semantic hits=%s",
            len(selected),
        )
        return selected

    logger.info("memory_retrieval_mode=keyword reason=semantic_miss")
    return keyword_select(query, world)


def retrieval_stats(
    mode: RetrievalMode,
    selected: list[str],
    *,
    fell_back: bool = False,
) -> dict[str, Any]:
    """飞轮 / span 元数据用。"""
    return {
        "retrieval_mode": "keyword" if fell_back else mode,
        "selected_count": len(selected),
        "fell_back": fell_back,
    }
