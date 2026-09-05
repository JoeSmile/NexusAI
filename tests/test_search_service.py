"""Task 84 — search_service lift + cap warn + web.search real path."""

from __future__ import annotations

import pytest

from packages.auth.models import TenantContext
from packages.search_service.failover import SearchOutcome
from packages.search_service.service import hits_to_web_search_results, search_web


@pytest.fixture
def tenant_user() -> TenantContext:
    return TenantContext(
        tenant_id="t-search",
        user_id="u1",
        role="user",
        extra_permissions=["chat:write"],
        is_cross_tenant=False,
    )


def test_hits_to_web_search_results_shape() -> None:
    out = SearchOutcome(
        hits=[
            {
                "title": "t",
                "url": "https://example.com/a",
                "snippet": "s",
                "publish_date": "2026-09-01",
                "source": "doubao",
            }
        ],
        provider="doubao",
    )
    rows = hits_to_web_search_results(out)
    assert rows[0]["title"] == "t"
    assert rows[0]["url"] == "https://example.com/a"
    assert rows[0]["snippet"] == "s"
    assert rows[0]["summary"] == "s"
    assert rows[0]["publish_time"] == "2026-09-01"
    assert rows[0]["source"] == "doubao"


def test_search_web_uses_mock_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCH_PROVIDER", "mock")
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("SEARCH_BACKUP_API_KEY", raising=False)
    monkeypatch.setattr(
        "packages.search_service.failover.get_sync_redis",
        lambda **_k: None,
    )
    out = search_web("考研政策", tenant_id="ing-t")
    assert out.hits
    assert out.hits[0]["source"].startswith("mock")
    assert "考研政策" in out.hits[0]["title"]


@pytest.mark.asyncio
async def test_web_search_handler_uses_to_thread(
    tenant_user: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.capability.builtin import handlers
    from packages.capability.builtin.handlers import invoke_builtin_handler
    from packages.search_service.service import search_web as search_web_fn

    called: dict[str, object] = {}

    async def _fake_to_thread(fn, *args, **kwargs):
        called["fn"] = fn
        called["args"] = args
        called["kwargs"] = kwargs
        return SearchOutcome(
            hits=[
                {
                    "title": "命中",
                    "url": "https://news.example/x",
                    "snippet": "摘要",
                    "publish_date": None,
                    "source": "mock_doubao",
                }
            ],
            provider="mock_doubao",
        )

    monkeypatch.setattr(handlers.asyncio, "to_thread", _fake_to_thread)
    result = await invoke_builtin_handler(
        "web.search", {"query": "考研"}, tenant_user
    )
    assert result.get("ok") is True
    assert called["fn"] is search_web_fn
    data = result["data"]
    assert data["results"][0]["title"] == "命中"
    assert data["results"][0]["summary"] == "摘要"
    assert data["results"][0]["publish_time"] is None
    assert "note" not in data


@pytest.mark.asyncio
async def test_web_search_does_not_fetch_result_url(
    tenant_user: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.capability.builtin.handlers import invoke_builtin_handler

    def _boom(*_a, **_k):
        raise AssertionError("must not HTTP-fetch result URLs")

    monkeypatch.setenv("SEARCH_PROVIDER", "mock")
    monkeypatch.setattr(
        "packages.search_service.failover.get_sync_redis",
        lambda **_k: None,
    )
    monkeypatch.setattr("packages.search_service.adapter.requests.get", _boom)
    monkeypatch.setattr("packages.search_service.adapter.requests.post", _boom)
    result = await invoke_builtin_handler(
        "web.search", {"query": "考研"}, tenant_user
    )
    assert result.get("ok") is True
    assert result["data"]["results"]
