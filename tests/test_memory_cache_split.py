"""S1b — split mem bundle cache into warm/cold keys; hot is uncached."""

from __future__ import annotations

import asyncio

import pytest

from packages.memory.memory_service import UnifiedMemoryService
from packages.pipeline.state import make_initial_state
from packages.plan.clarification import clear_pending
from packages.plan.coref import clear_session_coref
from tests.test_memory_ttfb import _Factory, _FakeRedis


def _patch_redis_and_pg(monkeypatch: pytest.MonkeyPatch, fake: _FakeRedis, counter: dict):
    monkeypatch.setattr("packages.redis_tools.get_sync_redis", lambda **_k: fake)
    monkeypatch.setattr(
        "packages.memory.memory_service.get_pg_session", lambda: _Factory(counter)
    )


def test_read_stores_warm_and_cold_keys_not_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    counter = {"queries": 0, "sessions": 0}
    _patch_redis_and_pg(monkeypatch, fake, counter)
    svc = UnifiedMemoryService(tenant_id="acme")
    asyncio.run(svc.read(user_id="u1", session_id="s1"))
    keys = list(fake.store)
    assert any(k.startswith("mem:warm:acme:u1") for k in keys)
    assert any(k.startswith("mem:cold:acme:u1:s1:") and k.endswith(":xcold") for k in keys)
    assert not any(k.startswith("mem:bundle:") for k in keys)
    assert not any(":hot:" in k or k.startswith("mem:hot:") for k in keys)


def test_write_turn_keeps_warm_and_cold_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    counter = {"queries": 0, "sessions": 0}
    _patch_redis_and_pg(monkeypatch, fake, counter)
    svc = UnifiedMemoryService(tenant_id="acme")
    asyncio.run(svc.read(user_id="u1", session_id="s1"))
    warm_keys = [k for k in fake.store if k.startswith("mem:warm:")]
    cold_keys = [k for k in fake.store if k.startswith("mem:cold:")]
    assert warm_keys and cold_keys
    asyncio.run(
        svc.write_turn(
            user_id="u1",
            session_id="s1",
            user_message="hi",
            assistant_message="yo",
        )
    )
    for k in warm_keys:
        assert k in fake.store
    for k in cold_keys:
        assert k in fake.store


def test_invalidate_warm_deletes_only_warm_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    counter = {"queries": 0, "sessions": 0}
    _patch_redis_and_pg(monkeypatch, fake, counter)
    svc = UnifiedMemoryService(tenant_id="acme")
    asyncio.run(svc.read(user_id="u1", session_id="s1"))
    cold_before = {k: fake.store[k] for k in fake.store if k.startswith("mem:cold:")}
    svc.invalidate_warm("u1")
    assert not any(k.startswith("mem:warm:") for k in fake.store)
    assert {k: fake.store[k] for k in fake.store if k.startswith("mem:cold:")} == cold_before


def test_drop_l1_narrative_invalidates_warm(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    counter = {"queries": 0, "sessions": 0}
    _patch_redis_and_pg(monkeypatch, fake, counter)
    monkeypatch.setattr(
        "packages.memory.hard_reset.delete_user_memory", lambda *_a, **_k: True
    )
    svc = UnifiedMemoryService(tenant_id="t1")
    asyncio.run(svc.read(user_id="u1", session_id="s1"))
    assert any(k.startswith("mem:warm:") for k in fake.store)
    from packages.memory.hard_reset import drop_l1_narrative

    drop_l1_narrative("t1", "u1", "s1")
    assert not any(k.startswith("mem:warm:") for k in fake.store)


def test_warm_cache_hit_preserves_warm_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr("packages.redis_tools.get_sync_redis", lambda **_k: fake)
    meta = {"pref": {"title": "tea", "source": "unified"}}

    def _hot(self, **_k):  # noqa: ANN001
        return []

    def _warm(self, **_k):  # noqa: ANN001
        return {"pref": "likes tea"}, dict(meta)

    def _cold(self, **_k):  # noqa: ANN001
        return []

    monkeypatch.setattr(UnifiedMemoryService, "_read_hot_sync", _hot)
    monkeypatch.setattr(UnifiedMemoryService, "_read_warm_sync", _warm)
    monkeypatch.setattr(UnifiedMemoryService, "_read_cold_sync", _cold)
    svc = UnifiedMemoryService(tenant_id="acme")
    b1 = asyncio.run(svc.read(user_id="u1", session_id="s1"))
    assert b1.warm_meta == meta

    def _boom(self, **_k):  # noqa: ANN001
        raise AssertionError("warm should be served from cache")

    monkeypatch.setattr(UnifiedMemoryService, "_read_warm_sync", _boom)
    b2 = asyncio.run(svc.read(user_id="u1", session_id="s1"))
    assert b2.warm == {"pref": "likes tea"}
    assert b2.warm_meta == meta


def test_sessions_share_warm_key_not_cold_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeRedis()
    counter = {"queries": 0, "sessions": 0}
    _patch_redis_and_pg(monkeypatch, fake, counter)
    svc = UnifiedMemoryService(tenant_id="acme")
    asyncio.run(svc.read(user_id="u1", session_id="s1"))
    asyncio.run(svc.read(user_id="u1", session_id="s2"))
    warm = [k for k in fake.store if k.startswith("mem:warm:")]
    cold = [k for k in fake.store if k.startswith("mem:cold:")]
    assert len(warm) == 1
    assert any(":s1:" in k and k.endswith(":xcold") for k in cold)
    assert any(":s2:" in k and k.endswith(":xcold") for k in cold)


@pytest.mark.asyncio
async def test_clear_pending_invalidates_warm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _Svc:
        def invalidate_warm(self, user_id: str) -> None:
            calls.append(user_id)

    monkeypatch.setattr(
        "packages.memory.memory_service.get_unified_memory_service",
        lambda **_k: _Svc(),
    )
    monkeypatch.setattr(
        "packages.database.vector_ops.delete_user_memory", lambda *_a, **_k: True
    )
    state = make_initial_state("t1", "u1", "s1", "ok")
    await clear_pending(state)
    assert calls == ["u1"]


@pytest.mark.asyncio
async def test_clear_session_coref_invalidates_warm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _Svc:
        def invalidate_warm(self, user_id: str) -> None:
            calls.append(user_id)

    monkeypatch.setattr(
        "packages.memory.memory_service.get_unified_memory_service",
        lambda **_k: _Svc(),
    )
    monkeypatch.setattr(
        "packages.database.vector_ops.delete_user_memory", lambda *_a, **_k: True
    )
    state = make_initial_state("t1", "u1", "s1", "ok")
    await clear_session_coref(state)
    assert calls == ["u1"]


@pytest.mark.asyncio
async def test_persist_structured_turn_delete_invalidates_warm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _Mem:
        def invalidate_warm(self, user_id: str) -> None:
            calls.append(user_id)

        def count_session_messages(self, **_k: object) -> int:
            return 1

        def list_session_messages_head_tail(self, **_k: object) -> list:
            return []

        async def write(self, *_a: object, **_k: object) -> dict:
            return {}

    monkeypatch.setattr("packages.memory.write_items.pronoun_hits", lambda _t: [])
    monkeypatch.setattr(
        "packages.memory.write_items.extract_structured_items", lambda _t: []
    )
    monkeypatch.setattr(
        "packages.memory.write_items.list_user_memories_by_prefix",
        lambda *_a, **_k: [{"key": "pending:s1:x", "value": "{}"}],
    )
    monkeypatch.setattr(
        "packages.memory.write_items.delete_user_memory", lambda *_a, **_k: True
    )
    from packages.memory.write_items import persist_structured_turn

    await persist_structured_turn(
        _Mem(),  # type: ignore[arg-type]
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        message="hi",
        trace_id="tr",
        aggregate=True,
    )
    assert calls == ["u1"]


def test_update_warm_importance_invalidates_warm(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    fake = _FakeRedis()
    monkeypatch.setattr("packages.redis_tools.get_sync_redis", lambda **_k: fake)

    class _Row:
        confidence = 0.5
        key = "pref"

    class _Session:
        def query(self, *_a, **_k):  # noqa: ANN001
            q = MagicMock()
            q.filter_by.return_value = q
            q.first.return_value = _Row()
            return q

        def commit(self) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_a):  # noqa: ANN001
            return None

    class _F:
        def Session(self) -> _Session:  # noqa: N802
            return _Session()

    monkeypatch.setattr("packages.memory.memory_service.get_pg_session", lambda: _F())
    svc = UnifiedMemoryService(tenant_id="acme")
    svc._store_warm("u1", {"pref": "x"}, {})
    assert any(k.startswith("mem:warm:") for k in fake.store)
    asyncio.run(svc.update_warm_importance("u1", "1", 0.9))
    assert not any(k.startswith("mem:warm:") for k in fake.store)
