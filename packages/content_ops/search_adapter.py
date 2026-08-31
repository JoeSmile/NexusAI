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
from typing import Any, Literal, Protocol, TypedDict
from urllib.parse import urlsplit, urlunsplit

import requests

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


DOUBAO_SEARCH_URL = "https://open.feedcoopapi.com/search_api/web_search"


def canonical_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    scheme = parts.scheme.lower() if parts.scheme else "https"
    if scheme == "http":
        scheme = "https"
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parts.path or "").rstrip("/")
    return urlunsplit((scheme, host, path, parts.query, ""))


def search_hits_to_hotspots(hits: list[SearchResult] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for hit in hits:
        title = str(hit.get("title") or "").strip()
        url = str(hit.get("url") or "").strip()
        snippet = str(hit.get("snippet") or "").strip()
        if not title and not url:
            continue
        cu = canonical_url(url)
        out.append(
            {
                "title": title or cu or "搜索结果",
                "summary": snippet,
                "summary_source": "snippet",
                "url": url,
                "canonical_url": cu,
                "source": str(hit.get("source") or "search"),
                "publish_date": hit.get("publish_date"),
                "score": 75,
                "category": "素质教育",
            }
        )
    return out


def _doubao_result_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    for path in (
        ("Result", "ResultList"),
        ("result", "ResultList"),
        ("Data", "ResultList"),
        ("data", "results"),
        ("Results",),
        ("results",),
    ):
        cur: Any = data
        ok = True
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and isinstance(cur, list):
            return [x for x in cur if isinstance(x, dict)]
    return []


class DoubaoSearchAdapter:
    """Volcengine Doubao Search Custom HTTP (official MCP host + PascalCase fields)."""

    name = "doubao"

    def search(self, req: SearchRequest) -> list[SearchResult]:
        key = (os.getenv("SEARCH_API_KEY") or "").strip()
        if not key:
            return []
        query = (req.query or "").strip()[:100]
        if not query:
            return []
        count = max(1, min(int(req.count or 10), 50))
        payload: dict[str, Any] = {
            "Query": query,
            "SearchType": "web",
            "Count": count,
            "TimeRange": recency_to_doubao(req.recency),
            "Filter": {"NeedUrl": True},
        }
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            DOUBAO_SEARCH_URL, headers=headers, json=payload, timeout=20
        )
        resp.raise_for_status()
        rows: list[SearchResult] = []
        for item in _doubao_result_rows(resp.json()):
            title = str(item.get("Title") or item.get("title") or "").strip()
            url = str(item.get("Url") or item.get("url") or "").strip()
            snippet = str(
                item.get("Snippet") or item.get("snippet") or item.get("Summary") or ""
            ).strip()
            if not title and not url:
                continue
            pub = item.get("PublishTime") or item.get("publish_date")
            rows.append(
                {
                    "title": title or url,
                    "url": url,
                    "snippet": snippet,
                    "publish_date": str(pub) if pub else None,
                    "source": self.name,
                }
            )
        return rows


def get_search_adapters() -> tuple[SearchAdapter, SearchAdapter]:
    provider = (os.getenv("SEARCH_PROVIDER") or "mock").strip().lower()
    backup: SearchAdapter = MockSearchAdapter("mock_zhipu")
    if provider == "doubao":
        return DoubaoSearchAdapter(), backup
    return MockSearchAdapter("mock_doubao"), backup
