"""47b slice0 — GET /api/chat/history tenant isolation + cursor pagination."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.auth.models import TenantContext
from backend.routers.chat_history import router as chat_history_router


def _row(
    *,
    id: int,
    tenant_id: str,
    user_id: str,
    session_id: str,
    role: str,
    content: str,
    client_message_id: str | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        role=role,
        content=content,
        client_message_id=client_message_id,
        created_at=datetime(2026, 8, 17, 12, 0, 0),
    )


class _Q:
    """In-memory stand-in that applies id cursor + DESC limit like the real query."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = list(rows)
        self._before_id: int | None = None
        self._limit = 11

    def filter(self, *args: Any) -> _Q:
        for a in args:
            right = getattr(a, "right", None)
            left = getattr(a, "left", None)
            op = getattr(getattr(a, "operator", None), "__name__", "") or str(
                getattr(a, "operator", "")
            )
            # ChatMessage.id < before_id
            if right is not None and left is not None and ("lt" in op or "<" in op):
                val = getattr(right, "value", right)
                try:
                    self._before_id = int(val)
                except (TypeError, ValueError):
                    pass
        return self

    def order_by(self, *_a: Any) -> _Q:
        return self

    def limit(self, n: int) -> _Q:
        self._limit = n
        return self

    def all(self) -> list[Any]:
        rows = self._rows
        if self._before_id is not None:
            rows = [r for r in rows if r.id < self._before_id]
        rows = sorted(rows, key=lambda r: r.id, reverse=True)
        return rows[: self._limit]


class _Session:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def query(self, *_a: Any) -> _Q:
        return _Q(self.rows)

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_a: Any) -> None:
        return None


class _Factory:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def Session(self) -> _Session:  # noqa: N802
        return _Session(self.rows)


def _client(rows: list[Any], tenant: TenantContext) -> TestClient:
    app = FastAPI()
    app.include_router(chat_history_router)

    async def _auth() -> TenantContext:
        return tenant

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    with patch(
        "backend.routers.chat_history.get_pg_session",
        return_value=_Factory(rows),
    ):
        yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def tenant_a() -> TenantContext:
    return TenantContext("t-a", "u1", "user", ["chat:write"], False)


def test_history_empty(tenant_a: TenantContext) -> None:
    gen = _client([], tenant_a)
    client = next(gen)
    try:
        r = client.get("/api/chat/history", params={"session_id": "workspace-chat"})
        assert r.status_code == 200
        assert r.json() == {"items": [], "has_more": False}
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_history_returns_client_message_id(tenant_a: TenantContext) -> None:
    rows = [
        _row(
            id=1,
            tenant_id="t-a",
            user_id="u1",
            session_id="workspace-chat",
            role="user",
            content="hi",
            client_message_id="cid-user-1",
        ),
        _row(
            id=2,
            tenant_id="t-a",
            user_id="u1",
            session_id="workspace-chat",
            role="assistant",
            content="hello",
            client_message_id="cid-asst-1",
        ),
    ]
    gen = _client(rows, tenant_a)
    client = next(gen)
    try:
        r = client.get(
            "/api/chat/history",
            params={"session_id": "workspace-chat", "limit": 10},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["has_more"] is False
        assert len(body["items"]) == 2
        assert body["items"][0]["client_message_id"] == "cid-user-1"
        assert body["items"][1]["client_message_id"] == "cid-asst-1"
        assert body["items"][1]["role"] == "assistant"
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_history_newest_page_not_oldest(tenant_a: TenantContext) -> None:
    """Without before_id, return the newest `limit` rows (asc within page)."""
    rows = [
        _row(
            id=i,
            tenant_id="t-a",
            user_id="u1",
            session_id="workspace-chat",
            role="user",
            content=f"m{i}",
            client_message_id=f"c{i}",
        )
        for i in range(1, 16)
    ]
    gen = _client(rows, tenant_a)
    client = next(gen)
    try:
        r = client.get(
            "/api/chat/history",
            params={"session_id": "workspace-chat", "limit": 10},
        )
        assert r.status_code == 200
        body = r.json()
        ids = [it["id"] for it in body["items"]]
        assert ids == list(range(6, 16))
        assert body["has_more"] is True
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_history_before_id_cursor(tenant_a: TenantContext) -> None:
    rows = [
        _row(
            id=i,
            tenant_id="t-a",
            user_id="u1",
            session_id="workspace-chat",
            role="user",
            content=f"m{i}",
            client_message_id=f"c{i}",
        )
        for i in range(1, 16)
    ]
    gen = _client(rows, tenant_a)
    client = next(gen)
    try:
        r = client.get(
            "/api/chat/history",
            params={"session_id": "workspace-chat", "limit": 10, "before_id": 6},
        )
        assert r.status_code == 200
        body = r.json()
        ids = [it["id"] for it in body["items"]]
        assert ids == list(range(1, 6))
        assert body["has_more"] is False
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_history_has_more_boundary_exact_limit(tenant_a: TenantContext) -> None:
    rows = [
        _row(
            id=i,
            tenant_id="t-a",
            user_id="u1",
            session_id="workspace-chat",
            role="user",
            content=f"m{i}",
            client_message_id=f"c{i}",
        )
        for i in range(1, 11)
    ]
    gen = _client(rows, tenant_a)
    client = next(gen)
    try:
        r = client.get(
            "/api/chat/history",
            params={"session_id": "workspace-chat", "limit": 10},
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 10
        assert body["has_more"] is False
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_history_has_more_when_one_extra(tenant_a: TenantContext) -> None:
    rows = [
        _row(
            id=i,
            tenant_id="t-a",
            user_id="u1",
            session_id="workspace-chat",
            role="user",
            content=f"m{i}",
            client_message_id=f"c{i}",
        )
        for i in range(1, 12)
    ]
    gen = _client(rows, tenant_a)
    client = next(gen)
    try:
        r = client.get(
            "/api/chat/history",
            params={"session_id": "workspace-chat", "limit": 10},
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 10
        assert body["has_more"] is True
        assert [it["id"] for it in body["items"]] == list(range(2, 12))
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_history_limit(tenant_a: TenantContext) -> None:
    rows = [
        _row(
            id=i,
            tenant_id="t-a",
            user_id="u1",
            session_id="workspace-chat",
            role="user",
            content=f"m{i}",
            client_message_id=f"c{i}",
        )
        for i in range(5)
    ]
    gen = _client(rows, tenant_a)
    client = next(gen)
    try:
        r = client.get(
            "/api/chat/history",
            params={"session_id": "workspace-chat", "limit": 2},
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 2
        assert [it["id"] for it in body["items"]] == [3, 4]
        assert body["has_more"] is True
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_timeline_has_more_like_history(tenant_a: TenantContext) -> None:
    rows = [
        _row(
            id=i,
            tenant_id="t-a",
            user_id="u1",
            session_id="workspace-chat",
            role="user",
            content=f"m{i}",
            client_message_id=f"c{i}",
        )
        for i in range(1, 12)
    ]
    gen = _client(rows, tenant_a)
    client = next(gen)
    try:
        r = client.get(
            "/api/chat/timeline",
            params={"session_id": "workspace-chat", "limit": 10},
        )
        assert r.status_code == 200
        body = r.json()
        ids = [it["id"] for g in body["groups"] for it in g["items"]]
        assert sorted(ids) == list(range(2, 12))
        assert body["has_more"] is True
        r2 = client.get(
            "/api/chat/timeline",
            params={"session_id": "workspace-chat", "limit": 10, "before_id": min(ids)},
        )
        assert r2.status_code == 200
        older = [it["id"] for g in r2.json()["groups"] for it in g["items"]]
        assert older == [1]
        assert r2.json()["has_more"] is False
    finally:
        try:
            next(gen)
        except StopIteration:
            pass
    gen = _client([], tenant_a)
    client = next(gen)
    try:
        r = client.get("/api/chat/timeline", params={"session_id": "workspace-chat"})
        assert r.status_code == 200
        body = r.json()
        assert body["groups"] == []
        assert "empty_hint" in body
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_timeline_empty_is_200(tenant_a: TenantContext) -> None:
    gen = _client([], tenant_a)
    client = next(gen)
    try:
        r = client.get("/api/chat/timeline", params={"session_id": "workspace-chat"})
        assert r.status_code == 200
        body = r.json()
        assert body["groups"] == []
        assert "empty_hint" in body
        assert body["has_more"] is False
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_timeline_groups_by_day(tenant_a: TenantContext) -> None:
    rows = [
        _row(
            id=1,
            tenant_id="t-a",
            user_id="u1",
            session_id="workspace-chat",
            role="user",
            content="day1",
            client_message_id="c1",
        ),
        _row(
            id=2,
            tenant_id="t-a",
            user_id="u1",
            session_id="workspace-chat",
            role="assistant",
            content="reply",
            client_message_id="c2",
        ),
    ]
    rows[0].created_at = datetime(2026, 8, 18, 10, 0, 0)
    rows[1].created_at = datetime(2026, 8, 19, 11, 0, 0)
    gen = _client(rows, tenant_a)
    client = next(gen)
    try:
        r = client.get("/api/chat/timeline", params={"session_id": "workspace-chat"})
        assert r.status_code == 200
        groups = r.json()["groups"]
        dates = [g["date"] for g in groups]
        assert dates == ["2026-08-19", "2026-08-18"]
        assert groups[0]["items"][0]["content"] == "reply"
        assert groups[1]["count"] == 1
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_search_empty_query_is_200(tenant_a: TenantContext) -> None:
    gen = _client([], tenant_a)
    client = next(gen)
    try:
        r = client.get(
            "/api/chat/search",
            params={"session_id": "workspace-chat", "q": "   "},
        )
        assert r.status_code == 200
        assert r.json() == {"items": []}
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_search_keyword_returns_snippet(tenant_a: TenantContext) -> None:
    rows = [
        _row(
            id=1,
            tenant_id="t-a",
            user_id="u1",
            session_id="workspace-chat",
            role="user",
            content="北京社保新规怎么解读",
            client_message_id="c1",
        ),
        _row(
            id=2,
            tenant_id="t-a",
            user_id="u1",
            session_id="workspace-chat",
            role="assistant",
            content="无关闲聊",
            client_message_id="c2",
        ),
    ]
    gen = _client(rows, tenant_a)
    client = next(gen)
    try:
        r = client.get(
            "/api/chat/search",
            params={"session_id": "workspace-chat", "q": "社保"},
        )
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == 1
        assert "社保" in items[0]["content"]
        assert items[0]["created_at"]
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_history_filters_by_tenant_user_in_query(tenant_a: TenantContext) -> None:
    """Router must pass tenant_id + user_id into filter (cross-tenant not returned)."""
    captured: dict[str, Any] = {}

    class _CaptureQ(_Q):
        def filter(self, *args: Any) -> _Q:
            captured.setdefault("filter_calls", []).append(args)
            return super().filter(*args)

    class _CaptureSession(_Session):
        def query(self, *_a: Any) -> _Q:
            return _CaptureQ([])

    class _CaptureFactory:
        def Session(self) -> _CaptureSession:  # noqa: N802
            return _CaptureSession([])

    app = FastAPI()
    app.include_router(chat_history_router)

    async def _auth() -> TenantContext:
        return tenant_a

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    with patch(
        "backend.routers.chat_history.get_pg_session",
        return_value=_CaptureFactory(),
    ):
        client = TestClient(app)
        r = client.get("/api/chat/history", params={"session_id": "workspace-chat"})
        assert r.status_code == 200
    app.dependency_overrides.clear()
    assert captured.get("filter_calls")
    # First filter call: tenant + session + or_(user)
    assert len(captured["filter_calls"][0]) == 3
