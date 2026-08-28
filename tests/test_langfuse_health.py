"""LangFuse health probe used by /health (local OSS v4 对接)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from packages import health as health_mod
from backend.observability import langfuse_client as lf


@pytest.fixture(autouse=True)
def _reset_langfuse_singleton():
    lf._lf = None
    lf._init_attempted = False
    yield
    lf._lf = None
    lf._init_attempted = False


def test_langfuse_local_status_does_not_urlopen(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://localhost:3001")
    monkeypatch.setattr(lf, "get_langfuse", lambda: object())

    with patch("urllib.request.urlopen", side_effect=AssertionError("no outbound")):
        got = health_mod.langfuse_local_status()
    assert got["status"] == "configured"
    assert got["host"] == "http://localhost:3001"


def test_sync_health_uses_local_langfuse(monkeypatch: pytest.MonkeyPatch):
    """GET /health must not urlopen LangFuse."""
    monkeypatch.setattr(
        health_mod, "langfuse_local_status", lambda: {"status": "configured", "host": "h"}
    )
    monkeypatch.setattr(
        health_mod,
        "langfuse_status",
        lambda: (_ for _ in ()).throw(AssertionError("remote probe")),
    )

    class _Sess:
        def execute(self, *_a, **_k):
            return MagicMock(fetchone=lambda: ("0.1",))

        def query(self, *_a, **_k):
            q = MagicMock()
            q.count.return_value = 0
            return q

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return None

    factory = MagicMock()
    factory.Session.return_value = _Sess()
    monkeypatch.setattr(health_mod, "get_pg_session", lambda: factory)

    import asyncio

    with patch("urllib.request.urlopen", side_effect=AssertionError("no outbound")):
        resp = asyncio.run(health_mod.health_check())
    body = resp.body
    assert b"configured" in body



def test_langfuse_status_up_when_public_health_ok(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://localhost:3001")
    monkeypatch.setattr(lf, "get_langfuse", lambda: object())

    resp = MagicMock()
    resp.status = 200
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    with patch("urllib.request.urlopen", return_value=resp):
        got = health_mod.langfuse_status()
    assert got["status"] == "up"
    assert got["host"] == "http://localhost:3001"


def test_langfuse_status_down_when_host_unreachable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://localhost:3001")
    monkeypatch.setattr(lf, "get_langfuse", lambda: object())

    with patch("urllib.request.urlopen", side_effect=OSError("refused")):
        got = health_mod.langfuse_status()
    assert got["status"] == "down"
    assert got["host"] == "http://localhost:3001"


def test_langfuse_status_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "0")
    assert health_mod.langfuse_status() == {"status": "disabled"}
    assert health_mod.langfuse_local_status() == {"status": "disabled"}
