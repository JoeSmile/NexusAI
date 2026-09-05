"""Task 79.2 — search failover + Redis spend caps."""

from __future__ import annotations

from unittest.mock import patch

from packages.search_service.adapter import SearchAdapterError, SearchRequest
from packages.search_service.failover import search_with_failover


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

    def set(self, key: str, value: object, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = 1
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
        "packages.search_service.failover.get_sync_redis",
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


def test_tenant_day_cap_warns_but_still_searches(monkeypatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(
        "packages.search_service.failover.get_sync_redis",
        lambda **_k: redis,
    )
    monkeypatch.setattr("packages.audit.write_audit_sync", lambda *_a, **_k: True)
    monkeypatch.setenv("SEARCH_GLOBAL_MONTH_CAP", "100")
    monkeypatch.setenv("SEARCH_TENANT_DAY_CAP", "1")
    monkeypatch.setenv("SEARCH_TENANT_MONTH_CAP", "100")
    primary = _Ok("doubao")
    backup = _Ok("zhipu")
    req = SearchRequest(query="考研", tenant_id="t1")
    first = search_with_failover(primary, backup, req)
    assert first.hits[0]["source"] == "doubao"
    assert first.degrade_code is None
    second = search_with_failover(primary, backup, req)
    assert second.hits[0]["source"] == "doubao"
    assert second.degrade_code == "SEARCH_CAP_EXCEEDED"
    assert backup.calls == 0
    assert primary.calls == 2


def test_over_global_cap_still_returns_hits(monkeypatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(
        "packages.search_service.failover.get_sync_redis",
        lambda **_k: redis,
    )
    monkeypatch.setattr("packages.audit.write_audit_sync", lambda *_a, **_k: True)
    monkeypatch.setenv("SEARCH_GLOBAL_MONTH_CAP", "1")
    monkeypatch.setenv("SEARCH_TENANT_DAY_CAP", "100")
    monkeypatch.setenv("SEARCH_TENANT_MONTH_CAP", "100")
    primary = _Ok("doubao")
    backup = _Ok("zhipu")
    req = SearchRequest(query="考研", tenant_id="t1")
    search_with_failover(primary, backup, req)
    out = search_with_failover(primary, backup, req)
    assert out.hits[0]["source"] == "doubao"
    assert out.degrade_code == "SEARCH_CAP_EXCEEDED"


def test_both_http_fail_returns_both_failed() -> None:
    with patch(
        "packages.search_service.failover.get_sync_redis",
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


def test_cap_plus_primary_fail_reports_failover_not_cap(monkeypatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(
        "packages.search_service.failover.get_sync_redis",
        lambda **_k: redis,
    )
    monkeypatch.setattr("packages.audit.write_audit_sync", lambda *_a, **_k: True)
    monkeypatch.setenv("SEARCH_GLOBAL_MONTH_CAP", "100")
    monkeypatch.setenv("SEARCH_TENANT_DAY_CAP", "1")
    monkeypatch.setenv("SEARCH_TENANT_MONTH_CAP", "100")
    ok = _Ok("doubao")
    boom = _Boom("doubao", 429)
    backup = _Ok("zhipu")
    req = SearchRequest(query="考研", tenant_id="t1")
    search_with_failover(ok, backup, req)
    out = search_with_failover(boom, backup, req)
    assert out.degrade_code == "SEARCH_FAILOVER"
    assert out.cap_warned is True
    assert out.hits[0]["source"] == "zhipu"


def test_zhipu_payload_uses_official_recency_filter() -> None:
    from packages.search_service.adapter import (
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

    with patch("packages.search_service.adapter.requests.post", _post), patch.dict(
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
