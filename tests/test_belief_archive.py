"""Task 77.3 — archive belief into warm memory on task end."""

from __future__ import annotations

import pytest

from packages.intent.belief_store import get_belief, set_belief
from packages.pipeline.nodes.intent_funnel import run_funnel
from packages.pipeline.state import make_initial_state


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.data[key] = value
        return True

    def delete(self, key: str) -> int:
        return 1 if self.data.pop(key, None) is not None else 0


@pytest.fixture
def belief_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(
        "packages.intent.belief_store.get_sync_redis",
        lambda **_k: fake,
    )
    return fake


@pytest.mark.asyncio
async def test_new_topic_archives_summary_and_deletes_belief(
    belief_redis: _FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_belief("t1", "u1", "s1", {"status": "ACTIVE", "slots": {"city": "北京"}, "summary": "订票去北京"})
    writes: list[tuple[str, dict]] = []

    class _Mem:
        async def write(self, tier: str, **payload):
            writes.append((tier, payload))
            return {"id": "w1", "tier": tier}

    monkeypatch.setattr(
        "packages.memory.memory_service.get_unified_memory_service",
        lambda **_k: _Mem(),
    )
    out = await run_funnel(make_initial_state("t1", "u1", "s1", "另外问报销"))
    assert out["is_new_topic"] is True
    assert get_belief("t1", "u1", "s1") is None
    assert writes
    assert writes[0][0] == "warm"
    assert "订票" in str(writes[0][1].get("value") or "")


@pytest.mark.asyncio
async def test_archive_failure_does_not_raise(
    belief_redis: _FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_belief("t1", "u1", "s1", {"status": "ACTIVE", "slots": {}, "summary": "订票"})

    class _Boom:
        async def write(self, *a, **k):
            raise RuntimeError("db down")

    monkeypatch.setattr(
        "packages.memory.memory_service.get_unified_memory_service",
        lambda **_k: _Boom(),
    )
    out = await run_funnel(make_initial_state("t1", "u1", "s1", "换个话题"))
    assert out["is_new_topic"] is True
    assert get_belief("t1", "u1", "s1") is None
