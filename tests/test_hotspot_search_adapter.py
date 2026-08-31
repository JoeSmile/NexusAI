"""Task 79.0 — search adapter contract + mock primary/backup."""

from __future__ import annotations

from packages.content_ops.search_adapter import (
    SearchRequest,
    SearchResult,
    get_search_adapters,
    recency_to_doubao,
    recency_to_zhipu,
)


def test_search_request_uses_recency_not_time_range() -> None:
    req = SearchRequest(query="考研调剂", recency="one_week", count=5)
    assert req.query == "考研调剂"
    assert req.recency == "one_week"
    assert not hasattr(req, "time_range")


def test_vendor_recency_maps_official_fields() -> None:
    # 火山 Custom：TimeRange = OneDay|OneWeek|… 不是 time_range
    # 智谱：search_recency_filter = oneWeek|… 不是 time_range
    assert recency_to_doubao("one_week") == "OneWeek"
    assert recency_to_zhipu("one_week") == "oneWeek"
    assert recency_to_doubao("one_day") == "OneDay"
    assert recency_to_zhipu("no_limit") == "noLimit"


def test_mock_primary_and_backup_are_distinct(monkeypatch) -> None:
    monkeypatch.setenv("SEARCH_PROVIDER", "mock")
    primary, backup = get_search_adapters()
    assert primary.name != backup.name
    req = SearchRequest(query="专升本政策", recency="one_week", count=3)
    a = primary.search(req)
    b = backup.search(req)
    assert a and b
    assert all(_is_result(row) for row in a)
    assert all(_is_result(row) for row in b)
    assert {row["source"] for row in a} == {primary.name}
    assert {row["source"] for row in b} == {backup.name}


def test_mock_does_not_fetch_result_urls(monkeypatch) -> None:
    monkeypatch.setenv("SEARCH_PROVIDER", "mock")
    primary, _backup = get_search_adapters()
    rows = primary.search(SearchRequest(query="考研", recency="one_week", count=2))
    assert all(row["url"].startswith("https://") for row in rows)
    # v1: adapter returns snippet only; never follows the URL
    assert all(row.get("snippet") for row in rows)


def test_spend_caps_are_configurable_not_free_500(monkeypatch) -> None:
    from packages.content_ops.search_adapter import search_cap_config

    monkeypatch.setenv("SEARCH_GLOBAL_MONTH_CAP", "2000")
    monkeypatch.setenv("SEARCH_TENANT_DAY_CAP", "80")
    monkeypatch.setenv("SEARCH_TENANT_MONTH_CAP", "800")
    caps = search_cap_config()
    assert caps["global_month"] == 2000
    assert caps["tenant_day"] == 80
    assert caps["tenant_month"] == 800
    assert 500 not in caps.values()


def _is_result(row: SearchResult) -> bool:
    return bool(
        row.get("title")
        and row.get("url")
        and "snippet" in row
        and "publish_date" in row
        and row.get("source")
    )
