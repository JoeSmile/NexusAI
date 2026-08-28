"""Hybrid tool search orchestration (Task 60)."""

from __future__ import annotations

import logging
import os
from typing import Any

from packages.tool_search.bm25 import BM25Index
from packages.tool_search.rrf import reciprocal_rank_fusion
from packages.tool_search.vector_index import VectorToolIndex

logger = logging.getLogger(__name__)

BM25_TOP_K = 20
VECTOR_TOP_K = 20
RRF_TOP_K = 12
_STABLE_FULL_EXPOSE = 10
_FALLBACK_MIN_HITS = 2

_INDEX: ToolSearchIndex | None = None


def hybrid_search_enabled() -> bool:
    return (os.getenv("TOOL_SEARCH_HYBRID_ENABLED", "1")).strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _cap_document(cap: dict[str, Any]) -> str:
    tags = cap.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    tag_text = " ".join(str(t) for t in tags)
    return " ".join(
        [
            str(cap.get("id") or ""),
            str(cap.get("name") or ""),
            str(cap.get("description") or ""),
            str(cap.get("kind") or ""),
            tag_text,
        ]
    ).strip()


def _fallback_ids(
    allowed: set[str],
    caps_by_id: dict[str, dict[str, Any]],
    *,
    limit: int = RRF_TOP_K,
) -> list[str]:
    """High-frequency baseline tools when recall is near-zero."""
    env = (os.getenv("TOOL_SEARCH_FALLBACK_IDS") or "").strip()
    if env:
        preferred = [x.strip() for x in env.split(",") if x.strip()]
    else:
        preferred = []
    ordered: list[str] = []
    for cid in preferred:
        if cid in allowed and cid not in ordered:
            ordered.append(cid)
    ranked = sorted(
        allowed,
        key=lambda cid: (
            0 if str(caps_by_id.get(cid, {}).get("kind") or "") in ("skill", "agent") else 1,
            cid,
        ),
    )
    for cid in ranked:
        if cid not in ordered:
            ordered.append(cid)
        if len(ordered) >= limit:
            break
    return ordered[:limit]


def _record_metrics(
    *,
    result_count: int,
    bm25_count: int,
    vector_count: int,
    zero_recall: bool,
) -> None:
    try:
        from packages.metrics import (
            tool_search_bm25_recall_total,
            tool_search_queries_total,
            tool_search_vector_recall_total,
            tool_search_zero_recall_total,
        )

        tool_search_queries_total.inc()
        tool_search_bm25_recall_total.inc(bm25_count)
        tool_search_vector_recall_total.inc(vector_count)
        if zero_recall or result_count < _FALLBACK_MIN_HITS:
            tool_search_zero_recall_total.inc()
    except Exception:
        logger.debug("tool_search metrics skipped", exc_info=True)


class ToolSearchIndex:
    """Global capability metadata index (BM25 + local vectors)."""

    def __init__(self) -> None:
        self._bm25 = BM25Index()
        self._vector = VectorToolIndex()
        self._meta: dict[str, dict[str, Any]] = {}

    def clear(self) -> None:
        self._bm25.clear()
        self._vector.clear()
        self._meta.clear()

    def upsert_cap(self, cap: dict[str, Any]) -> None:
        cid = str(cap.get("id") or "").strip()
        if not cid:
            return
        doc = _cap_document(cap)
        self._meta[cid] = dict(cap)
        self._bm25.upsert(cid, doc)
        self._vector.upsert(cid, doc)

    def remove_cap(self, cap_id: str) -> None:
        cid = str(cap_id or "").strip()
        if not cid:
            return
        self._meta.pop(cid, None)
        self._bm25.remove(cid)
        self._vector.remove(cid)

    def rebuild(self, caps: list[dict[str, Any]]) -> None:
        self.clear()
        for cap in caps:
            self.upsert_cap(cap)

    def search(
        self,
        query: str,
        *,
        allowed_ids: set[str] | None = None,
        top_k: int = RRF_TOP_K,
    ) -> list[dict[str, Any]]:
        allowed = allowed_ids or set(self._meta)
        if not allowed:
            _record_metrics(result_count=0, bm25_count=0, vector_count=0, zero_recall=True)
            return []

        bm25_hits = [
            cid
            for cid, _ in self._bm25.search(query, top_k=BM25_TOP_K)
            if cid in allowed
        ]
        vector_hits = [
            cid
            for cid, _ in self._vector.search(query, top_k=VECTOR_TOP_K)
            if cid in allowed
        ]
        merged_ids = reciprocal_rank_fusion(
            [bm25_hits, vector_hits],
            limit=top_k,
        )
        zero_recall = not bm25_hits and not vector_hits
        if len(merged_ids) < _FALLBACK_MIN_HITS:
            fallback = _fallback_ids(allowed, self._meta, limit=top_k)
            for cid in fallback:
                if cid not in merged_ids:
                    merged_ids.append(cid)
                if len(merged_ids) >= _FALLBACK_MIN_HITS:
                    break

        _record_metrics(
            result_count=len(merged_ids),
            bm25_count=len(bm25_hits),
            vector_count=len(vector_hits),
            zero_recall=zero_recall,
        )
        return [self._meta[cid] for cid in merged_ids if cid in self._meta]


def get_tool_search_index() -> ToolSearchIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = ToolSearchIndex()
    return _INDEX


def rebuild_tool_search_from_specs(specs: list[Any]) -> None:
    caps: list[dict[str, Any]] = []
    for spec in specs:
        nested = dict(getattr(spec, "spec", None) or {})
        caps.append(
            {
                "id": spec.id,
                "name": getattr(spec, "name", spec.id),
                "kind": str(getattr(spec, "kind", "") or ""),
                "description": str(nested.get("description") or spec.name),
                "tags": nested.get("tags") or [],
            }
        )
    get_tool_search_index().rebuild(caps)


def search_tools_hybrid(
    caps: list[dict[str, Any]],
    query: str,
    *,
    top_k: int = RRF_TOP_K,
    stable_threshold: int = _STABLE_FULL_EXPOSE,
) -> list[dict[str, Any]]:
    """Hybrid BM25 + vector RRF search over pre-filtered capability dicts."""
    if not caps:
        return []
    if len(caps) <= stable_threshold:
        return list(caps)

    index = get_tool_search_index()
    if not index._meta:
        index.rebuild(caps)

    allowed = {str(c.get("id") or "") for c in caps if c.get("id")}
    hits = index.search(query, allowed_ids=allowed, top_k=top_k)
    if hits:
        return hits

    # Index may be stale vs filtered caps — rebuild once and retry.
    index.rebuild(caps)
    return index.search(query, allowed_ids=allowed, top_k=top_k)
