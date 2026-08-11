"""Wave A A3 — dual_auth + require_permission accepts Bearer."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.core.auth import jwt_session as js
from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_permission


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-wave-a-min-32-bytes!!")
    monkeypatch.setenv("JWT_TTL_SECONDS", "3600")
    try:
        from config import get_settings

        get_settings.cache_clear()
    except Exception:
        pass
    yield
    try:
        from config import get_settings

        get_settings.cache_clear()
    except Exception:
        pass


def _patch_key_row(monkeypatch, *, role: str = "user"):
    row = SimpleNamespace(
        id=7,
        tenant_id="acme",
        user_id="alice",
        role=role,
        extra_permissions=[],
    )
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None
    session.execute.return_value.fetchone.return_value = row
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(
        "backend.database.pgvector_session.get_pg_session",
        lambda: factory,
    )
    return session


def _patch_session_perms(monkeypatch, perms=None):
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None
    session.execute.return_value.fetchone.return_value = SimpleNamespace(
        permissions=perms or []
    )
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(
        "backend.database.pgvector_session.get_pg_session",
        lambda: factory,
    )


@pytest.mark.asyncio
async def test_dual_bearer_and_api_key(monkeypatch):
    _patch_key_row(monkeypatch)
    key_ctx = await verify_human_or_legacy_key(
        authorization=None, api_key="cg_test_key"
    )
    assert key_ctx.credential_kind == "api_key"
    assert key_ctx.acting_user_id == "alice"

    _patch_session_perms(monkeypatch)
    token = js.issue_access_token(sub="bob", tid="acme", role="user")
    sess = await verify_human_or_legacy_key(
        authorization=f"Bearer {token}", api_key=None
    )
    assert sess.credential_kind == "human_session"
    assert sess.user_id == "bob"


def test_require_permission_accepts_bearer(monkeypatch):
    _patch_session_perms(monkeypatch)
    token = js.issue_access_token(sub="alice", tid="acme", role="user")

    app = FastAPI()

    @app.get("/protected")
    async def protected(
        tenant: TenantContext = Depends(require_permission("chat:write")),
    ):
        return {
            "ok": True,
            "kind": tenant.credential_kind,
            "user_id": tenant.user_id,
        }

    client = TestClient(app)
    r = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "human_session"
    assert body["user_id"] == "alice"


def test_require_permission_still_accepts_api_key(monkeypatch):
    _patch_key_row(monkeypatch)
    app = FastAPI()

    @app.get("/protected")
    async def protected(
        tenant: TenantContext = Depends(require_permission("chat:write")),
    ):
        return {"kind": tenant.credential_kind}

    client = TestClient(app)
    r = client.get("/protected", headers={"X-API-Key": "cg_test_key"})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "api_key"


def test_capabilities_list_accepts_bearer(monkeypatch):
    """Mount capability list route with dual auth."""
    from backend.routers import capability as cap_mod

    _patch_session_perms(monkeypatch)
    monkeypatch.setattr(
        cap_mod,
        "get_capability_registry",
        lambda: SimpleNamespace(
            list=lambda **kw: [],
        ),
    )
    token = js.issue_access_token(sub="alice", tid="acme", role="user")
    app = FastAPI()
    app.include_router(cap_mod.router)
    client = TestClient(app)
    r = client.get(
        "/api/capabilities",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 0
