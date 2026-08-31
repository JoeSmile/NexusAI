"""Task 77.1 — Redis belief store, TTL 30min, fail-open."""

from __future__ import annotations

import pytest

from packages.intent.belief_store import (
    BELIEF_TTL_SECONDS,
    belief_redis_key,
    delete_belief,
    get_belief,
    set_belief,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ex: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.data[key] = value
        if ex is not None:
            self.ex[key] = int(ex)
        return True

    def delete(self, key: str) -> int:
        existed = 1 if key in self.data else 0
        self.data.pop(key, None)
        self.ex.pop(key, None)
        return existed


@pytest.fixture
def redis_client(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(
        "packages.intent.belief_store.get_sync_redis",
        lambda **_k: fake,
    )
    return fake


def test_belief_key_shape_and_isolation() -> None:
    a = belief_redis_key("t1", "u1", "s1")
    b = belief_redis_key("t2", "u1", "s1")
    c = belief_redis_key("t1", "u2", "s1")
    d = belief_redis_key("t1", "u1", "s2")
    assert a.startswith("belief:cur:")
    assert len({a, b, c, d}) == 4


def test_get_set_delete_roundtrip(redis_client: _FakeRedis) -> None:
    payload = {"status": "ACTIVE", "slots": {"city": "北京"}, "summary": "订票"}
    assert set_belief("t1", "u1", "s1", payload) is True
    assert redis_client.ex[belief_redis_key("t1", "u1", "s1")] == BELIEF_TTL_SECONDS
    got = get_belief("t1", "u1", "s1")
    assert got is not None
    assert got["status"] == "ACTIVE"
    assert got["slots"]["city"] == "北京"
    assert get_belief("t1", "u1", "s2") is None
    assert delete_belief("t1", "u1", "s1") is True
    assert get_belief("t1", "u1", "s1") is None


def test_redis_down_returns_none_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "packages.intent.belief_store.get_sync_redis",
        lambda **_k: None,
    )
    assert get_belief("t1", "u1", "s1") is None
    assert set_belief("t1", "u1", "s1", {"status": "ACTIVE"}) is False
    assert delete_belief("t1", "u1", "s1") is False


def test_corrupt_json_treated_as_empty(redis_client: _FakeRedis) -> None:
    redis_client.data[belief_redis_key("t1", "u1", "s1")] = "not-json{"
    assert get_belief("t1", "u1", "s1") is None


def test_ttl_is_30_minutes() -> None:
    assert BELIEF_TTL_SECONDS == 30 * 60
