"""Wave A A2 — HS256 JWT issue/verify."""

from __future__ import annotations

import time

import pytest

from backend.core.auth import jwt_session as js


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-wave-a-min-32-bytes!!")
    monkeypatch.setenv("JWT_TTL_SECONDS", "3600")
    # clear settings cache if used
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


def test_issue_and_verify_roundtrip():
    token = js.issue_access_token(sub="alice", tid="acme", role="user")
    claims = js.verify_access_token(token)
    assert claims["sub"] == "alice"
    assert claims["tid"] == "acme"
    assert claims["role"] == "user"
    assert claims["jti"]
    assert "exp" in claims
    assert "permissions" not in claims


def test_tampered_token_rejected():
    token = js.issue_access_token(sub="alice", tid="acme", role="user")
    bad = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(ValueError, match="invalid_token"):
        js.verify_access_token(bad)


def test_expired_token_rejected(monkeypatch):
    monkeypatch.setenv("JWT_TTL_SECONDS", "1")
    try:
        from config import get_settings

        get_settings.cache_clear()
    except Exception:
        pass
    token = js.issue_access_token(sub="alice", tid="acme", role="user")
    time.sleep(1.2)
    with pytest.raises(ValueError, match="token_expired"):
        js.verify_access_token(token)


def test_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    try:
        from config import get_settings

        get_settings.cache_clear()
    except Exception:
        pass
    # Force empty settings jwt_secret
    monkeypatch.setenv("JWT_SECRET", "")
    try:
        from config import get_settings

        get_settings.cache_clear()
    except Exception:
        pass
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        js.issue_access_token(sub="a", tid="t", role="user")
