"""Unified web search entry (hotspot + web.search capability)."""

from __future__ import annotations

from packages.search_service.adapter import (
    Recency,
    SearchRequest,
    get_search_adapters,
)
from packages.search_service.failover import SearchOutcome, search_with_failover


def search_web(
    query: str,
    *,
    recency: Recency = "one_week",
    count: int = 10,
    tenant_id: str = "",
) -> SearchOutcome:
    """One paid search (counts as one cap unit). Does not fetch result URLs."""
    primary, backup = get_search_adapters()
    return search_with_failover(
        primary,
        backup,
        SearchRequest(
            query=query,
            recency=recency,
            count=count,
            tenant_id=tenant_id or "",
        ),
    )


def hits_to_web_search_results(outcome: SearchOutcome) -> list[dict]:
    rows: list[dict] = []
    for hit in outcome.hits:
        snippet = str(hit.get("snippet") or "")
        rows.append(
            {
                "title": str(hit.get("title") or ""),
                "url": str(hit.get("url") or ""),
                "snippet": snippet,
                "summary": snippet,
                "publish_time": hit.get("publish_date"),
                "source": str(hit.get("source") or ""),
            }
        )
    return rows
