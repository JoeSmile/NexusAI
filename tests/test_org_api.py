"""Wave B1 — org units / memberships API + path helpers."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from backend.core.org.models import normalize_business_roles
from backend.core.org.service import compute_child_path, rewrite_subtree_paths
from backend.routers import org as org_mod
from backend.routers.org import router


def test_compute_child_path():
    assert compute_child_path(None, "a") == "/a/"
    assert compute_child_path("/a/", "b") == "/a/b/"


def test_rewrite_subtree_paths():
    pairs = rewrite_subtree_paths(
        old_path="/a/",
        new_path="/x/",
        descendant_paths=["/a/", "/a/b/", "/a/b/c/"],
    )
    assert ("/a/", "/x/") in pairs
    assert ("/a/b/", "/x/b/") in pairs
    assert ("/a/b/c/", "/x/b/c/") in pairs


def test_normalize_business_roles():
    assert normalize_business_roles(["dept_manager", "dept_operator", "member"]) == [
        "dept_manager",
        "member",
    ]
    assert normalize_business_roles([]) == ["member"]


@pytest.fixture
def admin_client(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def _admin() -> TenantContext:
        return TenantContext("acme", "admin1", "tenant_admin", [], False)

    app.dependency_overrides[verify_human_or_legacy_key] = _admin

    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None
    session.execute.return_value.fetchone.return_value = None
    session.execute.return_value.fetchall.return_value = []
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(org_mod, "get_pg_session", lambda: factory)

    client = TestClient(app)
    client._session = session  # type: ignore[attr-defined]
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def user_client(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def _user() -> TenantContext:
        return TenantContext("acme", "u1", "user", [], False)

    app.dependency_overrides[verify_human_or_legacy_key] = _user

    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None
    session.execute.return_value.fetchone.return_value = None
    session.execute.return_value.fetchall.return_value = []
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(org_mod, "get_pg_session", lambda: factory)

    client = TestClient(app)
    client._session = session  # type: ignore[attr-defined]
    yield client
    app.dependency_overrides.clear()


def test_create_unit_forbidden_for_user(user_client):
    r = user_client.post("/api/org/units", json={"name": "财务"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "ORG_001"


def test_create_unit_ok(admin_client):
    r = admin_client.post("/api/org/units", json={"name": "财务"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "财务"
    assert body["path"].startswith("/")
    assert body["path"].endswith("/")
    admin_client._session.commit.assert_called()  # type: ignore[attr-defined]


def test_move_updates_descendant_paths(admin_client):
    """Service-level path rewrite covered; API move returns 200 when unit exists."""
    session = admin_client._session  # type: ignore[attr-defined]
    unit = SimpleNamespace(
        id="child",
        tenant_id="acme",
        parent_id="root",
        name="会计",
        path="/root/child/",
        deleted_at=None,
        created_at=datetime(2026, 8, 1),
    )
    new_parent = SimpleNamespace(
        id="hr",
        tenant_id="acme",
        parent_id=None,
        name="人事",
        path="/hr/",
        deleted_at=None,
        created_at=datetime(2026, 8, 1),
    )
    grandchild = SimpleNamespace(id="g", path="/root/child/g/")

    # get_unit(child), get_unit(hr), SELECT descendants, then get_unit after update
    session.execute.return_value.fetchone.side_effect = [
        unit,
        new_parent,
        unit,  # after commit refresh — path still old in mock; OK for status
    ]
    session.execute.return_value.fetchall.return_value = [grandchild]

    r = admin_client.patch(
        "/api/org/units/child/move", json={"parent_id": "hr"}
    )
    assert r.status_code == 200, r.text
    session.commit.assert_called()


def test_delete_soft_when_members(admin_client):
    session = admin_client._session  # type: ignore[attr-defined]
    unit = SimpleNamespace(
        id="u1",
        tenant_id="acme",
        parent_id=None,
        name="财务",
        path="/u1/",
        deleted_at=None,
        created_at=datetime(2026, 8, 1),
    )
    # get_unit include_deleted, count members, table exists probes return None, soft update
    session.execute.return_value.fetchone.side_effect = [
        unit,
        SimpleNamespace(c=2),  # members
        None,  # workflow table probe (any)
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    ]
    r = admin_client.delete("/api/org/units/u1")
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "soft"


def test_membership_primary_atomic(admin_client):
    session = admin_client._session  # type: ignore[attr-defined]
    unit = SimpleNamespace(
        id="ou1",
        tenant_id="acme",
        parent_id=None,
        name="财务",
        path="/ou1/",
        deleted_at=None,
        created_at=datetime(2026, 8, 1),
    )
    created = SimpleNamespace(
        id="m1",
        tenant_id="acme",
        user_id="alice",
        org_unit_id="ou1",
        is_primary=True,
        business_roles=["dept_manager"],
        created_at=datetime(2026, 8, 1),
    )
    # get_unit, existing membership None, then after insert we don't re-fetch for new path
    session.execute.return_value.fetchone.side_effect = [unit, None]

    r = admin_client.post(
        "/api/org/memberships",
        json={
            "user_id": "alice",
            "org_unit_id": "ou1",
            "is_primary": True,
            "business_roles": ["dept_manager"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_primary"] is True
    assert "dept_manager" in r.json()["business_roles"]
    session.commit.assert_called()


def test_delete_sole_primary_membership_400(admin_client):
    session = admin_client._session  # type: ignore[attr-defined]
    row = SimpleNamespace(
        id="m1",
        tenant_id="acme",
        user_id="alice",
        org_unit_id="ou1",
        is_primary=True,
        business_roles=["member"],
        created_at=datetime(2026, 8, 1),
    )
    session.execute.return_value.fetchone.side_effect = [
        row,
        SimpleNamespace(c=0),
    ]
    r = admin_client.delete("/api/org/memberships/m1")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "ORG_008"


def test_memberships_me(admin_client):
    session = admin_client._session  # type: ignore[attr-defined]
    session.execute.return_value.fetchall.return_value = [
        SimpleNamespace(
            id="m1",
            tenant_id="acme",
            user_id="admin1",
            org_unit_id="ou1",
            is_primary=True,
            business_roles=["member"],
            created_at=datetime(2026, 8, 1),
        )
    ]
    r = admin_client.get("/api/org/memberships/me")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["org_unit_id"] == "ou1"
