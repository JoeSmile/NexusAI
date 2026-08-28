"""Task 72 — model-scoped key pool + round-robin."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import backend.core.llm_credentials as llm_cred
from backend.core.key_repository import LLMKey
from backend.core.llm_credentials import get_key_chain_for_model, resolve_tenant_credential
from packages.llm_key_pool import pick_key_from_chain


class _RecordingSession:
    def __init__(self, *, fetchall=None):
        self._fetchall = fetchall if fetchall is not None else []
        self.execute = MagicMock(side_effect=self._execute)

    def _execute(self, sql, params=None):
        result = MagicMock()
        rows = self._fetchall if isinstance(self._fetchall, list) else []
        result.fetchall = lambda: rows
        return result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def _cred_row(
    *,
    id: int = 1,
    provider: str = "chat",
    allowed_models: list[str] | None = None,
    base_url: str = "https://api.example.com/v1",
    encrypted_key: str = "enc",
):
    return SimpleNamespace(
        id=id,
        tenant_id="t1",
        provider=provider,
        allowed_models=allowed_models or ["deepseek-v4-flash"],
        base_url=base_url,
        encrypted_key=encrypted_key,
        key_version=id,
        is_active=True,
        expires_at=None,
    )


@pytest.fixture
def decrypt_ok(monkeypatch):
    km = MagicMock()
    km.decrypt.side_effect = lambda enc: f"plain-{enc}"
    monkeypatch.setattr(llm_cred, "KeyManager", lambda: km)


def test_pick_key_round_robin_with_redis(monkeypatch):
    chain = [
        LLMKey("1", "t1", "chat", "https://a", "k1", 1, True, None),
        LLMKey("2", "t1", "chat", "https://b", "k2", 2, True, None),
    ]
    client = MagicMock()
    client.incr.side_effect = [1, 2, 3]
    monkeypatch.setattr(
        "packages.redis_tools.get_sync_redis",
        lambda decode_responses=True: client,
    )
    assert pick_key_from_chain(chain, tenant_id="t1", model="m1").id == "1"
    assert pick_key_from_chain(chain, tenant_id="t1", model="m1").id == "2"
    assert pick_key_from_chain(chain, tenant_id="t1", model="m1").id == "1"


def test_pick_key_no_redis_returns_first(monkeypatch):
    chain = [
        LLMKey("1", "t1", "chat", "https://a", "k1", 1, True, None),
        LLMKey("2", "t1", "chat", "https://b", "k2", 2, True, None),
    ]
    monkeypatch.setattr(
        "packages.redis_tools.get_sync_redis",
        lambda decode_responses=True: None,
    )
    assert pick_key_from_chain(chain, tenant_id="t1", model="m1").id == "1"
    assert pick_key_from_chain(chain, tenant_id="t1", model="m1").id == "1"


@pytest.mark.asyncio
async def test_get_key_chain_for_model_filters_allowed(monkeypatch, decrypt_ok):
    rows = [
        _cred_row(id=1, allowed_models=["deepseek-v4-flash"]),
        _cred_row(id=2, allowed_models=["other-model"]),
        _cred_row(id=3, allowed_models=["deepseek-v4-flash"]),
    ]
    session = _RecordingSession(fetchall=rows)
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(llm_cred, "get_pg_session", lambda: factory)

    chain = await get_key_chain_for_model("t1", "deepseek-v4-flash", limit=3)
    assert [k.id for k in chain] == ["1", "3"]


@pytest.mark.asyncio
async def test_get_key_chain_uses_cooldown_sql(monkeypatch, decrypt_ok):
    """D9: chain query includes cooldown filter."""
    session = _RecordingSession(fetchall=[_cred_row(id=9)])
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(llm_cred, "get_pg_session", lambda: factory)

    chain = await get_key_chain_for_model("t1", "deepseek-v4-flash")
    assert len(chain) == 1
    sql_text = str(session.execute.call_args[0][0])
    assert "last_failed_at" in sql_text


@pytest.mark.asyncio
async def test_resolve_tenant_credential_round_robin(monkeypatch, decrypt_ok):
    rows = [
        _cred_row(id=1),
        _cred_row(id=2),
    ]
    session = _RecordingSession(fetchall=rows)
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(llm_cred, "get_pg_session", lambda: factory)

    client = MagicMock()
    client.incr.side_effect = [1, 2]
    monkeypatch.setattr(
        "packages.redis_tools.get_sync_redis",
        lambda decode_responses=True: client,
    )

    k1 = await resolve_tenant_credential("t1", "deepseek-v4-flash")
    k2 = await resolve_tenant_credential("t1", "deepseek-v4-flash")
    assert k1.id == "1"
    assert k2.id == "2"
