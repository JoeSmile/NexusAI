"""Task 51 / S1b — load_memory Redis cache + warm inject cap."""

from __future__ import annotations

import asyncio
import fnmatch
from unittest.mock import MagicMock

from packages.memory.memory_service import MemoryBundle, UnifiedMemoryService


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gets = 0
        self.sets = 0

    def get(self, key: str) -> str | None:
        self.gets += 1
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.sets += 1
        self.store[key] = value
        return True

    def setex(self, key: str, _ttl: int, value: str) -> bool:
        return self.set(key, value, ex=_ttl)

    def scan_iter(self, match: str | None = None, count: int = 50):
        for k in list(self.store):
            if match is None or fnmatch.fnmatch(k, match):
                yield k

    def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                n += 1
        return n


class _CountingSession:
    def __init__(self, counter: dict) -> None:
        self.counter = counter

    def query(self, *_a, **_k):
        self.counter["queries"] += 1
        q = MagicMock()
        q.filter_by.return_value = q
        q.filter.return_value = q
        q.order_by.return_value = q
        q.limit.return_value = q
        q.all.return_value = []
        q.first.return_value = None
        q.count.return_value = 0
        return q

    def add(self, *_a, **_k) -> None:
        return None

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def execute(self, statement, *args, **kwargs):  # noqa: ANN001
        self.counter["queries"] += 1
        raise NotImplementedError(
            f"_CountingSession.execute() not stubbed for {statement!r}; "
            "add an explicit branch (do not return empty silently)"
        )

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None


class _Factory:
    def __init__(self, counter: dict) -> None:
        self.counter = counter
        self.counter.setdefault("sessions", 0)

    def Session(self) -> _CountingSession:  # noqa: N802
        self.counter["sessions"] += 1
        return _CountingSession(self.counter)


def test_read_second_hit_skips_warm_and_cold_db(monkeypatch) -> None:
    fake = _FakeRedis()
    counter = {"queries": 0, "sessions": 0}
    monkeypatch.setattr(
        "packages.redis_tools.get_sync_redis", lambda **_k: fake
    )
    monkeypatch.setattr(
        "packages.memory.memory_service.get_pg_session", lambda: _Factory(counter)
    )
    svc = UnifiedMemoryService(tenant_id="acme")
    b1 = asyncio.run(svc.read(user_id="u1", session_id="s1"))
    first_q = counter["queries"]
    first_sessions = counter["sessions"]
    assert first_q >= 3
    assert first_sessions >= 3
    b2 = asyncio.run(svc.read(user_id="u1", session_id="s1"))
    assert counter["queries"] == first_q + 1
    assert counter["sessions"] == first_sessions + 1
    assert b1.warm == b2.warm
    assert b1.cold == b2.cold
    assert fake.sets >= 1
    assert fake.gets >= 1


def test_write_turn_does_not_clear_warm_cold_cache(monkeypatch) -> None:
    fake = _FakeRedis()
    counter = {"queries": 0, "sessions": 0}
    monkeypatch.setattr(
        "packages.redis_tools.get_sync_redis", lambda **_k: fake
    )
    monkeypatch.setattr(
        "packages.memory.memory_service.get_pg_session", lambda: _Factory(counter)
    )
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
    after_write_q = counter["queries"]
    asyncio.run(svc.read(user_id="u1", session_id="s1"))
    # hot always hits DB; warm/cold stay cached so only +1 query
    assert counter["queries"] == after_write_q + 1


def test_read_without_redis_still_works(monkeypatch) -> None:
    counter = {"queries": 0, "sessions": 0}
    monkeypatch.setattr(
        "packages.redis_tools.get_sync_redis", lambda **_k: None
    )
    monkeypatch.setattr(
        "packages.memory.memory_service.get_pg_session", lambda: _Factory(counter)
    )
    svc = UnifiedMemoryService(tenant_id="acme")
    b = asyncio.run(svc.read(user_id="u1", session_id="s1"))
    assert isinstance(b, MemoryBundle)
    assert counter["queries"] > 0
    asyncio.run(svc.read(user_id="u1", session_id="s1"))
    assert counter["queries"] > 0


def test_read_include_cold_false_skips_cold_session(monkeypatch) -> None:
    fake = _FakeRedis()
    counter = {"queries": 0, "sessions": 0}
    monkeypatch.setattr(
        "packages.redis_tools.get_sync_redis", lambda **_k: fake
    )
    monkeypatch.setattr(
        "packages.memory.memory_service.get_pg_session", lambda: _Factory(counter)
    )
    svc = UnifiedMemoryService(tenant_id="acme")
    asyncio.run(
        svc.read(user_id="u1", session_id="s1", include_warm=True, include_cold=False)
    )
    assert counter["sessions"] == 2
    assert any(k.startswith("mem:warm:") for k in fake.store)
    assert not any(k.startswith("mem:cold:") for k in fake.store)


def test_assemble_caps_warm_at_30() -> None:
    svc = UnifiedMemoryService(tenant_id="t")
    warm = {f"fact:{i}": ("x" * 80) for i in range(50)}
    block = svc.assemble_prompt_block(MemoryBundle(warm=warm, hot=[], cold=[]))
    facts = [ln for ln in block.splitlines() if ln.startswith("- fact:")]
    assert len(facts) == 30
    assert len(block) < 20_000


def test_counting_session_execute_text_raises_not_silent() -> None:
    import pytest

    sess = _CountingSession({"queries": 0})
    with pytest.raises(NotImplementedError, match="not stubbed"):
        sess.execute("SELECT 1")
    assert sess.counter["queries"] == 1
