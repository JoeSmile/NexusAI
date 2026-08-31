"""Task 79.2 — search failover + Redis spend caps."""

from __future__ import annotations

from unittest.mock import patch

from packages.content_ops.search_adapter import SearchRequest
from packages.content_ops.search_failover import (
    SearchAdapterError,
    search_with_failover,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        if key not in self.data:
            return None
        return str(self.data[key])

    def incr(self, key: str) -> int:
        self.data[key] = int(self.data.get(key) or 0) + 1
        return self.data[key]

    def expire(self, key: str, ttl: int) -> bool:
        return True


class _Ok:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def search(self, req: SearchRequest):
        self.calls += 1
        return [
            {
                "title": f"{self.name} hit",
                "url": f"https://{self.name}.example/1",
                "snippet": "ok",
                "publish_date": None,
                "source": self.name,
            }
        ]


class _Boom:
    def __init__(self, name: str, status: int = 429) -> None:
        self.name = name
        self.calls = 0
        self.status = status

    def search(self, req: SearchRequest):
        self.calls += 1
        raise SearchAdapterError(f"http_{self.status}", status=self.status)


def test_primary_429_uses_backup(monkeypatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(
        "packages.content_ops.search_failover.get_sync_redis",
        lambda **_k: redis,
    )
    monkeypatch.setenv("SEARCH_GLOBAL_MONTH_CAP", "100")
    monkeypatch.setenv("SEARCH_TENANT_DAY_CAP", "100")
    monkeypatch.setenv("SEARCH_TENANT_MONTH_CAP", "100")
    primary = _Boom("doubao", 429)
    backup = _Ok("zhipu")
    out = search_with_failover(
        primary,
        backup,
        SearchRequest(query="考研", tenant_id="t1"),
    )
    assert primary.calls == 1
    assert backup.calls == 1
    assert out.hits[0]["source"] == "zhipu"
    assert out.degrade_code == "SEARCH_FAILOVER"


def test_tenant_day_cap_blocks_paid_search(monkeypatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(
        "packages.content_ops.search_failover.get_sync_redis",
        lambda **_k: redis,
    )
    monkeypatch.setenv("SEARCH_GLOBAL_MONTH_CAP", "100")
    monkeypatch.setenv("SEARCH_TENANT_DAY_CAP", "1")
    monkeypatch.setenv("SEARCH_TENANT_MONTH_CAP", "100")
    primary = _Ok("doubao")
    backup = _Ok("zhipu")
    req = SearchRequest(query="考研", tenant_id="t1")
    first = search_with_failover(primary, backup, req)
    assert first.hits[0]["source"] == "doubao"
    second = search_with_failover(primary, backup, req)
    assert second.hits == []
    assert second.degrade_code == "SEARCH_CAP_EXCEEDED"
    assert backup.calls == 0


def test_both_over_cap_returns_crawl_only_code(monkeypatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(
        "packages.content_ops.search_failover.get_sync_redis",
        lambda **_k: redis,
    )
    monkeypatch.setenv("SEARCH_GLOBAL_MONTH_CAP", "1")
    monkeypatch.setenv("SEARCH_TENANT_DAY_CAP", "100")
    monkeypatch.setenv("SEARCH_TENANT_MONTH_CAP", "100")
    primary = _Ok("doubao")
    backup = _Ok("zhipu")
    req = SearchRequest(query="考研", tenant_id="t1")
    search_with_failover(primary, backup, req)
    out = search_with_failover(primary, backup, req)
    assert out.hits == []
    assert out.degrade_code == "SEARCH_CAP_EXCEEDED"


def test_both_http_fail_returns_both_failed() -> None:
    with patch(
        "packages.content_ops.search_failover.get_sync_redis",
        lambda **_k: _FakeRedis(),
    ), patch.dict(
        "os.environ",
        {
            "SEARCH_GLOBAL_MONTH_CAP": "100",
            "SEARCH_TENANT_DAY_CAP": "100",
            "SEARCH_TENANT_MONTH_CAP": "100",
        },
        clear=False,
    ):
        out = search_with_failover(
            _Boom("doubao", 500),
            _Boom("zhipu", 500),
            SearchRequest(query="考研", tenant_id="t1"),
        )
    assert out.hits == []
    assert out.degrade_code == "SEARCH_BOTH_FAILED"


def test_zhipu_payload_uses_official_recency_filter() -> None:
    from packages.content_ops.search_adapter import (
        ZhipuSearchAdapter,
        recency_to_zhipu,
    )

    captured: dict = {}

    def _post(url, headers=None, json=None, timeout=None, **_k):
        captured["url"] = url
        captured["json"] = json
        resp = type("R", (), {})()
        resp.status_code = 200
        resp.json = lambda: {
            "search_result": [
                {
                    "title": "智谱条",
                    "content": "摘要",
                    "link": "https://example.com/z",
                    "publish_date": "2026-08-01",
                }
            ]
        }
        resp.raise_for_status = lambda: None
        return resp

    with patch("packages.content_ops.search_adapter.requests.post", _post), patch.dict(
        "os.environ", {"SEARCH_BACKUP_API_KEY": "zk-test"}, clear=False
    ):
        rows = ZhipuSearchAdapter().search(
            SearchRequest(query="专升本", recency="one_week", count=8)
        )
    body = captured["json"]
    assert captured["url"].endswith("/paas/v4/web_search")
    assert body["search_query"] == "专升本"
    assert body["search_engine"] == "search_std"
    assert body["search_intent"] is False
    assert body["search_recency_filter"] == recency_to_zhipu("one_week")
    assert "time_range" not in body
    assert rows[0]["source"] == "zhipu"
    assert rows[0]["url"] == "https://example.com/z"
