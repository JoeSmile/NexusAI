"""Public paid web search (Doubao/Zhipu/mock). Task 84 lift from content_ops."""

from packages.search_service.adapter import (
    DOUBAO_SEARCH_URL,
    ZHIPU_SEARCH_URL,
    DoubaoSearchAdapter,
    MockSearchAdapter,
    Recency,
    SearchAdapter,
    SearchAdapterError,
    SearchRequest,
    SearchResult,
    ZhipuSearchAdapter,
    canonical_url,
    get_search_adapters,
    recency_to_doubao,
    recency_to_zhipu,
    search_cap_config,
    search_hits_to_hotspots,
)
from packages.search_service.failover import SearchOutcome, search_with_failover
from packages.search_service.service import hits_to_web_search_results, search_web

__all__ = [
    "DOUBAO_SEARCH_URL",
    "ZHIPU_SEARCH_URL",
    "DoubaoSearchAdapter",
    "MockSearchAdapter",
    "Recency",
    "SearchAdapter",
    "SearchAdapterError",
    "SearchOutcome",
    "SearchRequest",
    "SearchResult",
    "ZhipuSearchAdapter",
    "canonical_url",
    "get_search_adapters",
    "hits_to_web_search_results",
    "recency_to_doubao",
    "recency_to_zhipu",
    "search_cap_config",
    "search_hits_to_hotspots",
    "search_web",
    "search_with_failover",
]
