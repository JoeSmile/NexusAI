"""F3 工具检索 — BM25 + 本地向量 RRF（Task 60）；小目录全量暴露。"""

from __future__ import annotations

import re
from typing import Any

from packages.tool_search.search import hybrid_search_enabled, search_tools_hybrid

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

DEFAULT_TOP_K = 12
_STABLE_FULL_EXPOSE = 10


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) >= 2}


def _search_keyword(
    caps: list[dict[str, Any]],
    query: str,
    *,
    top_k: int,
    stable_threshold: int,
) -> list[dict[str, Any]]:
    """Legacy keyword overlap scorer (fallback when hybrid disabled)."""
    if not caps:
        return []
    if len(caps) <= stable_threshold:
        return list(caps)
    qtok = _tokens(query)
    if not qtok:
        return caps[:top_k]

    scored: list[tuple[float, dict[str, Any]]] = []
    for cap in caps:
        text = " ".join(
            [
                str(cap.get("id") or ""),
                str(cap.get("name") or ""),
                str(cap.get("description") or ""),
                str(cap.get("kind") or ""),
            ]
        )
        ctok = _tokens(text)
        if not ctok:
            scored.append((0.0, cap))
            continue
        inter = len(qtok & ctok)
        score = inter / (len(qtok) ** 0.5)
        scored.append((score, cap))
    scored.sort(key=lambda x: (-x[0], str(x[1].get("id") or "")))
    return [c for _, c in scored[: max(1, top_k)]]


def search_capabilities(
    caps: list[dict[str, Any]],
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    stable_threshold: int = _STABLE_FULL_EXPOSE,
) -> list[dict[str, Any]]:
    """Hybrid retrieval (BM25 + local vector RRF) or legacy keyword overlap."""
    if hybrid_search_enabled():
        return search_tools_hybrid(
            caps,
            query,
            top_k=top_k,
            stable_threshold=stable_threshold,
        )
    return _search_keyword(
        caps,
        query,
        top_k=top_k,
        stable_threshold=stable_threshold,
    )
