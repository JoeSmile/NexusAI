"""Reciprocal Rank Fusion for dual-path tool recall (Task 60)."""

from __future__ import annotations

from collections.abc import Sequence


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[str]],
    *,
    limit: int = 12,
    k: int = 60,
) -> list[str]:
    """Merge ranked id lists with RRF; higher rank (earlier) scores more."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            if not doc_id:
                continue
            scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (k + rank))
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    cap = max(1, int(limit))
    return [doc_id for doc_id, _ in ordered[:cap]]
