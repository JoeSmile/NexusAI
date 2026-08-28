"""Task 52 S1 — TikHubConnector / DouyinAdapter unit tests (mocked httpx)."""

from __future__ import annotations

import json

import httpx
import pytest

from packages.social.adapters.douyin import (
    DouyinAdapter,
    extract_text_and_source,
)
from packages.social.connector import TikHubConnector
from packages.social.exceptions import (
    PlatformNotOpenError,
    TikHubBalanceError,
    TikHubConfigError,
)
from packages.social.http_client import CURL_UA, TikHubHttpClient


def _profile_payload(sec_uid: str = "MS4wLjABAAAAtest") -> dict:
    return {
        "code": 200,
        "data": {
            "user": {
                "sec_uid": sec_uid,
                "nickname": "姜胡说",
                "follower_count": 1234567,
                "total_favorited": 999,
                "aweme_count": 656,
                "avatar_thumb": {
                    "url_list": ["https://cdn.example/avatar.jpg"],
                },
            }
        },
    }


def _list_payload(n: int = 2, *, long_desc: bool = True) -> dict:
    awemes = []
    for i in range(n):
        desc = ("口播全文" + "字" * 120) if long_desc else f"短{i}"
        awemes.append(
            {
                "aweme_id": f"id{i}",
                "desc": desc,
                "create_time": 1700000000 + i,
                "statistics": {
                    "digg_count": 10 + i,
                    "comment_count": 1,
                    "share_count": 2,
                    "collect_count": 3,
                    "play_count": 0,
                },
                "video": {"duration": 12000},
            }
        )
    return {"code": 200, "data": {"aweme_list": awemes, "has_more": 1, "max_cursor": 99}}


def test_extract_desc_priority():
    text, src = extract_text_and_source({"desc": "a" * 100})
    assert src == "desc"
    assert len(text) == 100
    text, src = extract_text_and_source({"desc": "短", "caption": "b" * 100})
    assert src == "caption"
    text, src = extract_text_and_source(
        {"desc": "短", "subtitle": [{"text": "字幕全文"}]}
    )
    assert src == "subtitle"
    assert text == "字幕全文"


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("TIKHUB_API_KEY", raising=False)
    with pytest.raises(TikHubConfigError):
        TikHubHttpClient()


def test_probe_and_fetch_recent_single_page(monkeypatch):
    monkeypatch.setenv("TIKHUB_API_KEY", "test-key")
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers.get("user-agent") == CURL_UA
        assert request.headers.get("authorization") == "Bearer test-key"
        path = request.url.path
        if "fetch_user_profile_by_short_id" in path:
            return httpx.Response(200, json=_profile_payload())
        if "fetch_user_post_videos" in path:
            # must be single page — test later that only one list call
            return httpx.Response(200, json=_list_payload(3))
        if "fetch_multi_video_v2" in path:
            return httpx.Response(200, json={"code": 200, "data": {"aweme_details": []}})
        return httpx.Response(404, json={"code": 404})

    transport = httpx.MockTransport(handler)
    client = TikHubHttpClient(api_key="test-key", transport=transport, sleep=lambda _s: None)
    conn = TikHubConnector(client=client, sleep=lambda _s: None)

    acct = conn.probe("douyin", "jianghushuo")
    assert acct.external_id.startswith("MS4w")
    assert acct.nickname == "姜胡说"
    assert acct.follower_count == 1234567
    assert acct.avatar_url and "avatar" in acct.avatar_url

    items = conn.fetch_recent("douyin", "jianghushuo", acct.external_id, enrich=False)
    assert len(items) == 3
    assert items[0].content_source == "desc"
    assert items[0].like_count == 10
    assert items[0].duration_s == 12

    list_calls = [c for c in calls if "fetch_user_post_videos" in c.url.path]
    assert len(list_calls) == 1
    assert list_calls[0].url.params.get("count") == "20"
    assert list_calls[0].url.params.get("max_cursor") == "0"


def test_fetch_recent_honors_limit(monkeypatch):
    monkeypatch.setenv("TIKHUB_API_KEY", "test-key")
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_list_payload(3))

    transport = httpx.MockTransport(handler)
    client = TikHubHttpClient(api_key="test-key", transport=transport, sleep=lambda _s: None)
    conn = TikHubConnector(client=client, sleep=lambda _s: None)
    conn.fetch_recent("douyin", "jianghushuo", "SEC", enrich=False, limit=35)
    list_calls = [c for c in calls if "fetch_user_post_videos" in c.url.path]
    assert len(list_calls) == 1
    assert list_calls[0].url.params.get("count") == "35"


def test_fetch_detail_bare_array_body(monkeypatch):
    monkeypatch.setenv("TIKHUB_API_KEY", "k")
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            bodies.append(request.content)
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {
                        "aweme_details": [
                            {
                                "aweme_id": "x1",
                                "desc": "短",
                                "subtitle": [{"subtitle": "完整字幕文案这里"}],
                                "statistics": {},
                            }
                        ]
                    },
                },
            )
        return httpx.Response(404, json={})

    client = TikHubHttpClient(
        api_key="k",
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
    )
    adapter = DouyinAdapter()
    out = adapter.fetch_detail(client, ["x1", "x2"], sleep=lambda _s: None)
    assert len(out) == 1
    assert out[0].content_source == "subtitle"
    parsed = json.loads(bodies[0].decode())
    assert parsed == ["x1", "x2"]  # bare array, not {"items": ...}


def test_402_raises_balance_error(monkeypatch):
    monkeypatch.setenv("TIKHUB_API_KEY", "k")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"detail": {"code": 402, "message": "no credit"}}
        )

    client = TikHubHttpClient(
        api_key="k",
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
    )
    with pytest.raises(TikHubBalanceError) as ei:
        client.get("/douyin/web/fetch_user_profile_by_short_id", {"short_id": "x"})
    assert "tikhub.io" in str(ei.value).lower() or "充值" in str(ei.value)


def test_retry_on_please_retry(monkeypatch):
    monkeypatch.setenv("TIKHUB_API_KEY", "k")
    n = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        n["i"] += 1
        if n["i"] < 3:
            return httpx.Response(400, json={"detail": "Please retry"})
        return httpx.Response(200, json=_profile_payload())

    waits: list[float] = []
    client = TikHubHttpClient(
        api_key="k",
        transport=httpx.MockTransport(handler),
        sleep=lambda s: waits.append(s),
    )
    d = client.get("/douyin/web/fetch_user_profile_by_short_id", {"short_id": "x"})
    assert d["code"] == 200
    assert n["i"] == 3
    assert waits == [3.0, 6.0]


def test_platform_not_open():
    with pytest.raises(PlatformNotOpenError):
        TikHubConnector(api_key="k").probe("xiaohongshu", "abc")
