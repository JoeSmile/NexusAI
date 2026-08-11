"""Wave A A2 — verify_session Depends."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.core.auth import jwt_session as js
from backend.core.auth import session_auth as sa


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


@pytest.mark.asyncio
async def test_verify_session_ok(monkeypatch):
    token = js.issue_access_token(sub="alice", tid="acme", role="user")

    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None
    session.execute.return_value.fetchone.return_value = SimpleNamespace(
        permissions=["kb:read"]
    )
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(
        "backend.database.pgvector_session.get_pg_session",
        lambda: factory,
    )

    ctx = await sa.verify_session(authorization=f"Bearer {token}")
    assert ctx.credential_kind == "human_session"
    assert ctx.user_id == "alice"
    assert ctx.acting_user_id == "alice"
    assert ctx.tenant_id == "acme"
    assert ctx.role == "user"
    assert ctx.key_id is None
    assert "kb:read" in ctx.extra_permissions


@pytest.mark.asyncio
async def test_verify_session_missing_header():
    with pytest.raises(HTTPException) as ei:
        await sa.verify_session(authorization=None)
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_session_bad_token():
    with pytest.raises(HTTPException) as ei:
        await sa.verify_session(authorization="Bearer not-a-jwt")
    assert ei.value.status_code == 401
