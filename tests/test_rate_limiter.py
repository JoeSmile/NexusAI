"""Chat QPS 限流：Redis 分钟桶，跨进程共享（替换进程内 TokenBucket）。"""

from __future__ import annotations

import pytest


class _FakeRedis:
    def __init__(self) -> None:
        self.n: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.n[key] = self.n.get(key, 0) + 1
        return self.n[key]

    def expire(self, key: str, ttl: int) -> None:
        self.expires[key] = ttl


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(
        "packages.redis_tools.get_sync_redis", lambda **_k: fake
    )
    return fake


def test_chat_limit_shared_across_calls(fake_redis: _FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_RATE_LIMIT_PER_MIN", "2")
    from packages.rate_limiter import check_rate_limit

    assert check_rate_limit("t1") is True
    assert check_rate_limit("t1") is True
    assert check_rate_limit("t1") is False
    assert check_rate_limit("t2") is True


def test_chat_limit_sets_ttl(fake_redis: _FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_RATE_LIMIT_PER_MIN", "10")
    from packages.rate_limiter import check_rate_limit

    check_rate_limit("t1")
    assert fake_redis.expires
    assert all(ttl == 70 for ttl in fake_redis.expires.values())


def test_chat_limit_redis_down_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_RATE_LIMIT_PER_MIN", "1")
    monkeypatch.setattr(
        "packages.redis_tools.get_sync_redis", lambda **_k: None
    )
    from packages.rate_limiter import check_rate_limit

    for _ in range(50):
        assert check_rate_limit("t1") is True


def test_chat_limit_disabled(fake_redis: _FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_RATE_LIMIT_PER_MIN", "0")
    from packages.rate_limiter import check_rate_limit

    for _ in range(5):
        assert check_rate_limit("t1") is True
    assert fake_redis.n == {}
