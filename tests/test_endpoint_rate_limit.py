"""Task 52 P1-5 endpoint rate limit."""

from __future__ import annotations


def test_endpoint_limit_independent_tenants(monkeypatch) -> None:
    class _R:
        def __init__(self) -> None:
            self.n: dict[str, int] = {}

        def incr(self, key: str) -> int:
            self.n[key] = self.n.get(key, 0) + 1
            return self.n[key]

        def expire(self, *_a, **_k) -> None:
            return None

    fake = _R()
    monkeypatch.setattr(
        "backend.core.redis_tools.get_sync_redis", lambda **_k: fake
    )
    from backend.core.rate_limiter import check_endpoint_rate_limit

    assert check_endpoint_rate_limit("t1", "dig", limit_per_min=1) is None
    assert check_endpoint_rate_limit("t1", "dig", limit_per_min=1) == 60
    assert check_endpoint_rate_limit("t2", "dig", limit_per_min=1) is None


def test_endpoint_limit_redis_down_allows(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.core.redis_tools.get_sync_redis", lambda **_k: None
    )
    from backend.core.rate_limiter import check_endpoint_rate_limit

    assert check_endpoint_rate_limit("t1", "dig", limit_per_min=1) is None
