"""Tenant LLM credential resolve + key repo no-env."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import packages.key_repository as key_repo
import packages.llm_credentials as llm_cred
from packages.errors import NexusAIException
from packages.llm_credentials import (
    list_available_models,
    resolve_chat_model_for_request,
    resolve_tenant_credential,
)


class _RecordingSession:
    def __init__(self, *, fetchall=None):
        self.calls: list[tuple[str, dict[str, object] | None]] = []
        self._fetchall = fetchall if fetchall is not None else []

    def execute(self, sql, params=None):
        sql_s = str(sql)
        self.calls.append((sql_s, params))
        result = MagicMock()
        rows = self._fetchall if isinstance(self._fetchall, list) else []
        result.fetchall = lambda: rows
        result.fetchone = lambda: rows[0] if rows else None
        return result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def _patch_repo_session(monkeypatch, session: _RecordingSession) -> None:
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(key_repo, "get_pg_session", lambda: factory)


def _cred_row(
    *,
    provider: str = "chat",
    allowed_models: list[str] | None = None,
    base_url: str = "https://api.example.com/v1",
    encrypted_key: str = "enc",
    id: int = 1,
):
    return SimpleNamespace(
        id=id,
        tenant_id="t1",
        provider=provider,
        allowed_models=allowed_models or ["deepseek-v4-flash"],
        base_url=base_url,
        encrypted_key=encrypted_key,
        key_version=1,
        is_active=True,
        expires_at=None,
    )


@pytest.fixture
def decrypt_ok(monkeypatch):
    km = MagicMock()
    km.decrypt.side_effect = lambda enc: f"plain-{enc}"
    monkeypatch.setattr(key_repo, "KeyManager", lambda: km)
    monkeypatch.setattr(llm_cred, "KeyManager", lambda: km)


@pytest.mark.asyncio
async def test_resolve_no_rows_is_model_not_allowed(monkeypatch):
    session = _RecordingSession(fetchall=[])
    monkeypatch.setattr(
        "packages.llm_credentials.get_pg_session",
        lambda: MagicMock(Session=lambda: session),
    )

    with pytest.raises(NexusAIException) as ei:
        await resolve_tenant_credential("t1", "deepseek-v4-flash")
    assert ei.value.code == "LLM_KEY_002"


@pytest.mark.asyncio
async def test_resolve_model_not_allowed(monkeypatch):
    session = _RecordingSession(
        fetchall=[_cred_row(allowed_models=["deepseek-v4-flash"])]
    )
    monkeypatch.setattr(
        "packages.llm_credentials.get_pg_session",
        lambda: MagicMock(Session=lambda: session),
    )

    with pytest.raises(NexusAIException) as ei:
        await resolve_tenant_credential("t1", "qwen-plus")
    assert ei.value.code == "LLM_KEY_002"


@pytest.mark.asyncio
async def test_get_key_chain_no_env_fallback(monkeypatch, decrypt_ok):
    session = _RecordingSession(fetchall=[])
    _patch_repo_session(monkeypatch, session)
    monkeypatch.setattr(key_repo, "_cooldown_seconds", lambda: 60)
    monkeypatch.setenv("LLM_API_KEY", "sk-env-fallback")

    repo = key_repo.LLMKeyRepository()
    chain = await repo.get_key_chain("t1", "deepseek", allow_env_fallback=False)
    assert chain == []


@pytest.mark.asyncio
async def test_get_key_chain_env_fallback_default(monkeypatch, decrypt_ok):
    session = _RecordingSession(fetchall=[])
    _patch_repo_session(monkeypatch, session)
    monkeypatch.setattr(key_repo, "_cooldown_seconds", lambda: 60)
    monkeypatch.setenv("LLM_API_KEY", "sk-env-fallback")
    monkeypatch.setattr(
        key_repo.LLMKeyRepository,
        "_env_fallback",
        lambda self, tenant_id, provider: key_repo.LLMKey(
            id="fallback",
            tenant_id=tenant_id,
            provider=provider,
            base_url="",
            api_key="sk-env-fallback",
            key_version=0,
            is_active=True,
            expires_at=None,
        ),
    )

    repo = key_repo.LLMKeyRepository()
    chain = await repo.get_key_chain("t1", "default", allow_env_fallback=True)
    assert len(chain) == 1
    assert chain[0].id == "fallback"
    assert chain[0].api_key == "sk-env-fallback"


@pytest.mark.asyncio
async def test_query_chain_filters_owner_user_id(monkeypatch, decrypt_ok):
    session = _RecordingSession(fetchall=[])
    _patch_repo_session(monkeypatch, session)
    monkeypatch.setattr(key_repo, "_cooldown_seconds", lambda: 60)

    repo = key_repo.LLMKeyRepository()
    await repo.get_key_chain("t1", "deepseek", allow_env_fallback=False)

    sql, _ = session.calls[0]
    assert "owner_user_id IS NULL" in sql


@pytest.mark.asyncio
async def test_resolve_success_by_model(monkeypatch, decrypt_ok):
    cred_session = _RecordingSession(
        fetchall=[
            _cred_row(
                provider="chat",
                allowed_models=["deepseek-v4-flash"],
                base_url="https://api.deepseek.com/v1",
            )
        ]
    )
    monkeypatch.setattr(
        "packages.llm_credentials.get_pg_session",
        lambda: MagicMock(Session=lambda: cred_session),
    )

    key = await resolve_tenant_credential("t1", "deepseek-v4-flash")
    assert key.api_key == "plain-enc"
    assert key.base_url == "https://api.deepseek.com/v1"


@pytest.mark.asyncio
async def test_resolve_empty_base_url_missing(monkeypatch, decrypt_ok):
    cred_session = _RecordingSession(
        fetchall=[
            _cred_row(
                allowed_models=["deepseek-v4-flash"],
                base_url="",
            )
        ]
    )
    monkeypatch.setattr(
        "packages.llm_credentials.get_pg_session",
        lambda: MagicMock(Session=lambda: cred_session),
    )

    with pytest.raises(NexusAIException) as ei:
        await resolve_tenant_credential("t1", "deepseek-v4-flash")
    assert ei.value.code == "LLM_KEY_001"


@pytest.mark.asyncio
async def test_list_available_models_chat_only(monkeypatch):
    session = _RecordingSession(
        fetchall=[
            _cred_row(
                id=1,
                provider="chat",
                allowed_models=["deepseek-v4-flash"],
            ),
            _cred_row(
                id=2,
                provider="chat",
                allowed_models=["qwen-plus"],
            ),
            _cred_row(
                id=3,
                provider="embedding",
                allowed_models=["text-embedding-3-small"],
            ),
            _cred_row(
                id=4,
                provider="deepseek",
                allowed_models=["legacy-model"],
            ),
        ]
    )
    monkeypatch.setattr(
        "packages.llm_credentials.get_pg_session",
        lambda: MagicMock(Session=lambda: session),
    )

    items = await list_available_models("t1")
    models = {i["model"] for i in items}
    assert models == {"deepseek-v4-flash", "qwen-plus", "legacy-model"}
    assert "text-embedding-3-small" not in models
    assert all(i["series"] == "chat" for i in items)
    assert all(i["configured"] is True for i in items)


@pytest.mark.asyncio
async def test_resolve_chat_model_auto_first_when_empty(monkeypatch):
    session = _RecordingSession(
        fetchall=[
            _cred_row(provider="chat", allowed_models=["qwen2.5:7b"]),
        ]
    )
    monkeypatch.setattr(
        "packages.llm_credentials.get_pg_session",
        lambda: MagicMock(Session=lambda: session),
    )

    model = await resolve_chat_model_for_request("t1", None)
    assert model == "qwen2.5:7b"


@pytest.mark.asyncio
async def test_resolve_chat_model_honors_valid_request(monkeypatch):
    session = _RecordingSession(
        fetchall=[
            _cred_row(id=1, provider="chat", allowed_models=["model-a"]),
            _cred_row(id=2, provider="chat", allowed_models=["model-b"]),
        ]
    )
    monkeypatch.setattr(
        "packages.llm_credentials.get_pg_session",
        lambda: MagicMock(Session=lambda: session),
    )

    assert await resolve_chat_model_for_request("t1", "model-b") == "model-b"


@pytest.mark.asyncio
async def test_resolve_chat_model_replaces_stale_request(monkeypatch):
    session = _RecordingSession(
        fetchall=[
            _cred_row(provider="chat", allowed_models=["only-model"]),
        ]
    )
    monkeypatch.setattr(
        "packages.llm_credentials.get_pg_session",
        lambda: MagicMock(Session=lambda: session),
    )

    assert await resolve_chat_model_for_request("t1", "stale-model") == "only-model"


@pytest.mark.asyncio
async def test_resolve_chat_model_missing_raises(monkeypatch):
    session = _RecordingSession(fetchall=[])
    monkeypatch.setattr(
        "packages.llm_credentials.get_pg_session",
        lambda: MagicMock(Session=lambda: session),
    )

    with pytest.raises(NexusAIException) as ei:
        await resolve_chat_model_for_request("t1", "")
    assert ei.value.code == "LLM_KEY_004"


@pytest.mark.asyncio
async def test_get_key_chain_tenant_only_skips_global(monkeypatch, decrypt_ok):
    session = _RecordingSession(fetchall=[])
    _patch_repo_session(monkeypatch, session)
    monkeypatch.setattr(key_repo, "_cooldown_seconds", lambda: 60)

    repo = key_repo.LLMKeyRepository()
    await repo.get_key_chain(
        "t1", "deepseek", allow_env_fallback=False, tenant_only=True
    )

    tenant_ids = {params["tid"] for _, params in session.calls if params}
    assert tenant_ids == {"t1"}
    assert "*" not in tenant_ids


@pytest.mark.asyncio
async def test_model_router_missing_tenant_key_raises(monkeypatch):
    from packages.errors import NexusAIException
    from packages.pipeline.state import make_initial_state

    async def _boom(tenant_id, model):
        raise NexusAIException("LLM_KEY_001", "tenant_llm_key_missing")

    monkeypatch.setattr(
        "packages.pipeline.nodes.model_router.resolve_tenant_credential",
        _boom,
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.model_router.resolve_short_path_skill",
        lambda state: None,
    )
    from packages.pipeline.nodes.model_router import model_router

    state = make_initial_state(
        "t1", "u1", "s1", "hello", preferred_model="deepseek-v4-flash"
    )
    state["intent"] = "default"
    state["intent_confidence"] = 0.1

    out = await model_router(state)
    assert out["error_code"] == "LLM_KEY_001"
    assert out["finish_reason"] == "error"


@pytest.mark.asyncio
async def test_model_router_resolves_tenant_credential(monkeypatch):
    from packages.key_repository import LLMKey
    from packages.pipeline.state import make_initial_state

    key = LLMKey(
        id="42",
        tenant_id="t1",
        provider="chat",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-test",
        key_version=1,
        is_active=True,
        expires_at=None,
    )

    async def _resolve(tenant_id, model):
        assert tenant_id == "t1"
        assert model == "deepseek-v4-flash"
        return key

    monkeypatch.setattr(
        "packages.pipeline.nodes.model_router.resolve_tenant_credential",
        _resolve,
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.model_router.resolve_short_path_skill",
        lambda state: None,
    )
    from packages.pipeline.nodes.model_router import model_router

    state = make_initial_state(
        "t1", "u1", "s1", "hello", preferred_model="deepseek-v4-flash"
    )
    state["intent"] = "default"
    state["intent_confidence"] = 0.1

    out = await model_router(state)
    assert out["selected_model"] == "deepseek-v4-flash"
    assert out["llm_api_key"] == "sk-test"
    assert out["llm_key_id"] == "42"
    assert out["finish_reason"] == "routed_to_llm"
