"""47b slice1 — feedback bookmark / reaction API."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.auth.models import TenantContext
from backend.routers import feedback as feedback_mod
from backend.routers.feedback import router as feedback_router


@pytest.fixture
def tenant() -> TenantContext:
    return TenantContext("acme", "u1", "user", [], False)


@pytest.fixture
def admin() -> TenantContext:
    return TenantContext("acme", "admin1", "tenant_admin", [], False)


def _app(tenant: TenantContext) -> FastAPI:
    app = FastAPI()
    app.include_router(feedback_router)

    async def _auth() -> TenantContext:
        return tenant

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    return app


def test_submit_ignores_body_user_id(tenant: TenantContext) -> None:
    saved: dict[str, Any] = {}

    def _save(**kwargs: Any) -> SimpleNamespace:
        saved.update(kwargs)
        return SimpleNamespace(
            id=9,
            session_id=kwargs["session_id"],
            feedback_type=kwargs["feedback_type"],
            rating=kwargs["rating"],
            client_message_id=kwargs.get("client_message_id"),
            created_at=datetime(2026, 8, 17),
        )

    db = MagicMock()
    db.save_feedback.side_effect = lambda **kw: _save(**kw)
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)

    app = _app(tenant)
    with patch.object(feedback_mod, "DatabaseManager", return_value=db):
        client = TestClient(app)
        r = client.post(
            "/feedback/",
            json={
                "session_id": "workspace-chat",
                "user_id": "attacker",
                "client_message_id": "cid-1",
                "feedback_type": "helpful",
            },
        )
    assert r.status_code == 200
    assert saved["user_id"] == "u1"
    assert saved["tenant_id"] == "acme"
    assert saved["rating"] == 5
    assert r.json()["feedback_id"] == 9


def test_bookmark_requires_bot_response(tenant: TenantContext) -> None:
    app = _app(tenant)
    client = TestClient(app)
    r = client.post(
        "/feedback/",
        json={
            "session_id": "workspace-chat",
            "client_message_id": "cid-b",
            "feedback_type": "bookmark",
        },
    )
    assert r.status_code == 422


def test_mine_and_delete(tenant: TenantContext) -> None:
    row = SimpleNamespace(
        id=3,
        session_id="workspace-chat",
        client_message_id="cid-1",
        feedback_type="bookmark",
        rating=None,
        comment="",
        user_message="",
        bot_response="hello",
        created_at=datetime(2026, 8, 17),
    )
    db = MagicMock()
    db.list_my_feedback.return_value = ([row], 1)
    db.delete_feedback_owned.return_value = True
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)

    app = _app(tenant)
    with patch.object(feedback_mod, "DatabaseManager", return_value=db):
        client = TestClient(app)
        r = client.get("/feedback/mine", params={"type": "bookmark", "session_id": "workspace-chat"})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["client_message_id"] == "cid-1"

        d = client.delete("/feedback/mine/3")
        assert d.status_code == 204
        db.delete_feedback_owned.assert_called_with(
            feedback_id=3, tenant_id="acme", user_id="u1"
        )


def test_delete_missing_404(tenant: TenantContext) -> None:
    db = MagicMock()
    db.delete_feedback_owned.return_value = False
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    app = _app(tenant)
    with patch.object(feedback_mod, "DatabaseManager", return_value=db):
        client = TestClient(app)
        assert client.delete("/feedback/mine/99").status_code == 404


def test_statistics_excludes_bookmark_call(admin: TenantContext) -> None:
    db = MagicMock()
    db.get_feedback_statistics.return_value = {
        "total_count": 2,
        "avg_rating": 3.0,
        "by_type": [{"type": "helpful", "count": 2, "avg_rating": 5.0}],
    }
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    app = _app(admin)
    with patch.object(feedback_mod, "DatabaseManager", return_value=db):
        client = TestClient(app)
        r = client.get("/feedback/statistics")
        assert r.status_code == 200
        db.get_feedback_statistics.assert_called_with(tenant_id="acme")


def test_list_passes_tenant(admin: TenantContext) -> None:
    db = MagicMock()
    db.get_all_feedback.return_value = []
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    app = _app(admin)
    with patch.object(feedback_mod, "DatabaseManager", return_value=db):
        client = TestClient(app)
        r = client.get("/feedback/list")
        assert r.status_code == 200
        db.get_all_feedback.assert_called_with(
            feedback_type=None, limit=100, tenant_id="acme"
        )


def test_u1_reaction_switch_single_row() -> None:
    """SQLite-compatible upsert path: helpful → irrelevant stays one row."""
    from backend.database.models import DatabaseManager, UserFeedback

    class _S:
        def __init__(self) -> None:
            self.rows: list[Any] = []
            self._id = 1

        def get_bind(self) -> SimpleNamespace:
            return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        def query(self, model: Any) -> Any:
            assert model is UserFeedback
            q = MagicMock()

            def _filter(*_a: Any, **_k: Any) -> Any:
                return q

            q.filter.side_effect = _filter
            q.filter_by.side_effect = _filter

            def _first() -> Any:
                for r in self.rows:
                    if r.feedback_type in ("helpful", "irrelevant"):
                        return r
                return None

            q.first.side_effect = _first
            return q

        def add(self, obj: Any) -> None:
            if getattr(obj, "id", None) is None:
                obj.id = self._id
                self._id += 1
            self.rows.append(obj)

        def commit(self) -> None:
            return None

        def refresh(self, obj: Any) -> None:
            return None

    sess = _S()
    mgr = DatabaseManager.__new__(DatabaseManager)
    mgr.db = sess  # type: ignore[attr-defined]

    a = mgr.save_feedback(
        "s",
        "u1",
        None,
        "helpful",
        5,
        "",
        "",
        "",
        tenant_id="t1",
        client_message_id="cid",
    )
    b = mgr.save_feedback(
        "s",
        "u1",
        None,
        "irrelevant",
        1,
        "",
        "",
        "",
        tenant_id="t1",
        client_message_id="cid",
    )
    assert a is b
    assert b.feedback_type == "irrelevant"
    assert len([r for r in sess.rows if r.feedback_type in ("helpful", "irrelevant")]) == 1
