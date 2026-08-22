"""F3 工具检索 — capability 关键词 top-K（Task 56）。"""

from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

DEFAULT_TOP_K = 10
_STABLE_FULL_EXPOSE = 10


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) >= 2}


def search_capabilities(
    caps: list[dict[str, Any]],
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    stable_threshold: int = _STABLE_FULL_EXPOSE,
) -> list[dict[str, Any]]:
    """按 query 与 name/id/description 分词交集打分；小目录全量暴露。"""
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
