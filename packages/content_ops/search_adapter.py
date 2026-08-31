"""Task 79 — paid web search adapters (platform keys, not tenant LLM).

Official field maps (do not invent ``time_range``):

* Volcengine Doubao Search Custom — ``TimeRange`` =
  ``OneDay|OneWeek|OneMonth|OneYear``
  https://www.volcengine.com/docs/87772/2272953
* Zhipu Web Search — ``search_recency_filter`` =
  ``oneDay|oneWeek|oneMonth|oneYear|noLimit``
  https://docs.bigmodel.cn/api-reference/工具-api/网络搜索
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

Recency = Literal["one_day", "one_week", "one_month", "one_year", "no_limit"]
ProviderName = Literal["doubao", "zhipu", "mock"]

_DOUBAO_RECENCY: dict[str, str] = {
    "one_day": "OneDay",
    "one_week": "OneWeek",
    "one_month": "OneMonth",
    "one_year": "OneYear",
    "no_limit": "OneYear",
}
_ZHIPU_RECENCY: dict[str, str] = {
    "one_day": "oneDay",
    "one_week": "oneWeek",
    "one_month": "oneMonth",
    "one_year": "oneYear",
    "no_limit": "noLimit",
}


class SearchResult(TypedDict):
    title: str
    url: str
    snippet: str
    publish_date: str | None
    source: str


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    recency: Recency = "one_week"
    count: int = 10


class SearchAdapter(Protocol):
    name: str

    def search(self, req: SearchRequest) -> list[SearchResult]:
        """Return snippets only. v1 must not follow result URLs."""
        ...


def recency_to_doubao(recency: str) -> str:
    return _DOUBAO_RECENCY.get(recency, "OneWeek")


def recency_to_zhipu(recency: str) -> str:
    return _ZHIPU_RECENCY.get(recency, "oneWeek")


def search_cap_config() -> dict[str, int]:
    """Paid spend caps. Never treat 500 as a free quota."""

    def _int(name: str, default: int) -> int:
        raw = (os.getenv(name) or "").strip()
        if not raw:
            return default
        try:
            return max(1, int(raw))
        except ValueError:
            return default

    return {
        "global_month": _int("SEARCH_GLOBAL_MONTH_CAP", 2000),
        "tenant_day": _int("SEARCH_TENANT_DAY_CAP", 80),
        "tenant_month": _int("SEARCH_TENANT_MONTH_CAP", 800),
    }


class MockSearchAdapter:
    """Deterministic primary/backup stand-in (slice 0). No HTTP."""

    def __init__(self, name: str) -> None:
        self.name = name

    def search(self, req: SearchRequest) -> list[SearchResult]:
        q = (req.query or "热点").strip() or "热点"
        n = max(1, min(int(req.count or 10), 10))
        host = "mock-doubao.example" if "doubao" in self.name else "mock-zhipu.example"
        out: list[SearchResult] = []
        for i in range(n):
            out.append(
                {
                    "title": f"{q} 动态 {i + 1}",
                    "url": f"https://{host}/item/{i + 1}",
                    "snippet": f"{q} 官方口径摘要（mock {self.name}）",
                    "publish_date": None,
                    "source": self.name,
                }
            )
        return out


def get_search_adapters() -> tuple[SearchAdapter, SearchAdapter]:
    provider = (os.getenv("SEARCH_PROVIDER") or "mock").strip().lower()
    if provider == "mock" or provider not in ("doubao", "zhipu"):
        return MockSearchAdapter("mock_doubao"), MockSearchAdapter("mock_zhipu")
    # Live HTTP adapters land in 79.1 / 79.2; mock pair keeps tests isolated.
    return MockSearchAdapter("mock_doubao"), MockSearchAdapter("mock_zhipu")
