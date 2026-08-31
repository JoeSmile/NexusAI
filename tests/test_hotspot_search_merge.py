"""Task 79.1 — canonical URL merge + Doubao search payload."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from packages.content_ops.hotspot import merge_hotspot_pool
from packages.content_ops.search_adapter import (
    DoubaoSearchAdapter,
    SearchRequest,
    canonical_url,
    recency_to_doubao,
    search_hits_to_hotspots,
)


def test_canonical_url_strips_www_fragment_slash() -> None:
    assert (
        canonical_url("HTTP://WWW.Example.com/path/?q=1#frag")
        == "https://example.com/path?q=1"
    )
    assert canonical_url("https://example.com/a/") == "https://example.com/a"
    assert canonical_url("") == ""


def test_merge_prefers_canonical_url_over_title() -> None:
    pool, new_n, skipped = merge_hotspot_pool(
        [
            {
                "title": "标题甲",
                "summary": "a",
                "score": 70,
                "canonical_url": "https://example.com/same",
            }
        ],
        [
            {
                "title": "完全不同的标题乙",
                "summary": "b",
                "score": 91,
                "canonical_url": "https://www.example.com/same/",
            }
        ],
    )
    assert new_n == 0
    assert skipped == 1
    assert len(pool) == 1
    assert pool[0]["score"] == 91
    assert pool[0]["title"] == "完全不同的标题乙"


def test_search_hits_mark_snippet_source() -> None:
    items = search_hits_to_hotspots(
        [
            {
                "title": "考研大纲",
                "url": "https://www.moe.gov.cn/a/",
                "snippet": "教育部发布",
                "publish_date": "2026-08-01",
                "source": "doubao",
            }
        ]
    )
    assert items[0]["summary"] == "教育部发布"
    assert items[0]["summary_source"] == "snippet"
    assert items[0]["canonical_url"] == canonical_url("https://www.moe.gov.cn/a/")
    assert items[0]["url"] == "https://www.moe.gov.cn/a/"


def test_doubao_payload_uses_official_timerange_not_time_range() -> None:
    captured: dict = {}

    def _post(url, headers=None, json=None, timeout=None, **_k):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "Result": {
                "ResultList": [
                    {
                        "Title": "政策",
                        "Url": "https://example.com/p",
                        "Snippet": "摘要",
                        "PublishTime": "2026-08-01",
                    }
                ]
            }
        }
        resp.raise_for_status = MagicMock()
        return resp

    with patch("packages.content_ops.search_adapter.requests.post", _post), patch.dict(
        "os.environ", {"SEARCH_API_KEY": "sk-test"}, clear=False
    ):
        rows = DoubaoSearchAdapter().search(
            SearchRequest(query="考研", recency="one_week", count=5)
        )
    payload = captured["json"]
    assert captured["url"] == "https://open.feedcoopapi.com/search_api/web_search"
    assert payload["Query"] == "考研"
    assert payload["Count"] == 5
    assert payload["SearchType"] == "web"
    assert payload["TimeRange"] == recency_to_doubao("one_week")
    assert "time_range" not in payload
    filt = payload.get("Filter") or {}
    assert filt.get("NeedContent") is not True
    assert filt.get("NeedUrl") is True
    assert rows[0]["title"] == "政策"
    assert rows[0]["source"] == "doubao"
    assert rows[0]["snippet"] == "摘要"


def test_topic_agent_merges_search_when_keywords_present() -> None:
    from packages.content_ops.hotspot import _topic_agent_items

    crawl = {
        "items": [
            {
                "title": "官网考研报名",
                "summary": "列表页",
                "url": "https://chsi.com.cn/a",
                "score": 80,
            }
        ],
        "raw_count": 1,
        "deduped_count": 1,
        "skipped_duplicates": 0,
        "source_reports": [],
        "per_source": 5,
    }
    hits = [
        {
            "title": "搜索补全条",
            "url": "https://news.example.com/k",
            "snippet": "全网摘要",
            "publish_date": None,
            "source": "doubao",
        }
    ]

    class _Ad:
        name = "doubao"

        def search(self, req):
            assert "考研" in req.query
            return hits

    with patch(
        "packages.content_ops.hotspot_crawl.crawl_hotspots", return_value=crawl
    ), patch(
        "packages.content_ops.search_adapter.get_search_adapters",
        return_value=(_Ad(), _Ad()),
    ):
        items, meta = _topic_agent_items(
            org_profile={},
            categories=None,
            keywords="考研",
            exclude_keywords=None,
            region=None,
        )
    titles = {str(it.get("title")) for it in items}
    assert "官网考研报名" in titles
    assert "搜索补全条" in titles
    search_row = next(it for it in items if it.get("title") == "搜索补全条")
    assert search_row.get("summary_source") == "snippet"
