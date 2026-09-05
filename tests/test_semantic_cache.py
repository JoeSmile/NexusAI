"""Task 72 切片 4 — 语义缓存（默认 OFF）。"""

from __future__ import annotations

import json
import time

import pytest

from packages.pipeline.cache import semantic_cache as sc
from packages.pipeline.state import make_initial_state


class _FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    def get(self, key: str) -> str | None:
        return self.kv.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.kv[key] = value

    def sadd(self, key: str, *values: str) -> None:
        self.sets.setdefault(key, set()).update(values)

    def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    def expire(self, key: str, ttl: int) -> None:
        return None


def _embed_bucket(text: str) -> list[float]:
    t = (text or "").lower()
    vec = [0.0] * 1024
    if "python" in t:
        vec[0] = 1.0
    elif "java" in t:
        vec[1] = 1.0
    else:
        vec[2] = 1.0
    return vec


@pytest.fixture(autouse=True)
def _reset() -> None:
    sc.reset_semantic_cache_for_tests()
    yield
    sc.reset_semantic_cache_for_tests()


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    r = _FakeRedis()
    monkeypatch.setattr(sc, "_redis", lambda: r)
    return r


def test_default_disabled_no_hit(fake_redis: _FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEMANTIC_CACHE_ENABLED", raising=False)
    state = make_initial_state("t1", "u1", "s1", "what is python")
    state["selected_model"] = "deepseek-v4-flash"
    state["intent"] = "qa"
    assert sc.lookup(state) is None


def test_paraphrase_hit(
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMANTIC_CACHE_ENABLED", "1")
    monkeypatch.setattr(
        "packages.database.embeddings.embed_text",
        lambda text, tenant_id=None: _embed_bucket(text),
    )

    state = make_initial_state("t1", "u1", "s1", "what is python")
    state["selected_model"] = "deepseek-v4-flash"
    state["intent"] = "qa"
    sc.upsert(state, "Python is a programming language.")

    state2 = make_initial_state("t1", "u1", "s2", "tell me about python")
    state2["selected_model"] = "deepseek-v4-flash"
    state2["intent"] = "qa"
    hit = sc.lookup(state2)
    assert hit == "Python is a programming language."


def test_different_model_miss(
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMANTIC_CACHE_ENABLED", "1")
    monkeypatch.setattr(
        "packages.database.embeddings.embed_text",
        lambda text, tenant_id=None: _embed_bucket(text),
    )

    state = make_initial_state("t1", "u1", "s1", "what is python")
    state["selected_model"] = "model-a"
    state["intent"] = "qa"
    sc.upsert(state, "answer-a")

    state2 = make_initial_state("t1", "u1", "s2", "tell me about python")
    state2["selected_model"] = "model-b"
    state2["intent"] = "qa"
    assert sc.lookup(state2) is None


def test_context_hash_isolation(
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMANTIC_CACHE_ENABLED", "1")
    monkeypatch.setattr(
        "packages.database.embeddings.embed_text",
        lambda text, tenant_id=None: _embed_bucket(text),
    )

    state = make_initial_state("t1", "u1", "s1", "what is python")
    state["selected_model"] = "m1"
    state["intent"] = "qa"
    state["memory_prompt_block"] = "user likes cats"
    sc.upsert(state, "with cats context")

    state2 = make_initial_state("t1", "u1", "s2", "tell me about python")
    state2["selected_model"] = "m1"
    state2["intent"] = "qa"
    state2["memory_prompt_block"] = ""
    assert sc.lookup(state2) is None


def test_try_apply_sets_finish_reason(
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMANTIC_CACHE_ENABLED", "1")
    monkeypatch.setattr(
        "packages.database.embeddings.embed_text",
        lambda text, tenant_id=None: _embed_bucket(text),
    )

    state = make_initial_state("t1", "u1", "s1", "what is python")
    state["selected_model"] = "m1"
    state["intent"] = "qa"
    sc.upsert(state, "cached answer")

    state2 = make_initial_state("t1", "u1", "s2", "explain python")
    state2["selected_model"] = "m1"
    state2["intent"] = "qa"
    assert sc.try_apply_semantic_cache(state2) is True
    assert state2["finish_reason"] == "semantic_cache_hit"
    assert state2["response"] == "cached answer"


def test_expired_entry_miss(
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMANTIC_CACHE_ENABLED", "1")
    monkeypatch.setattr(
        "packages.database.embeddings.embed_text",
        lambda text, tenant_id=None: _embed_bucket(text),
    )

    scope = sc.scope_key(
        tenant_id="t1",
        model="m1",
        prompt_version="1",
        intent="qa",
        context_hash="-",
    )
    entry_id = "abc123"
    payload = json.dumps(
        {
            "vec": _embed_bucket("python"),
            "response": "stale",
            "expires_at": time.time() - 10,
        }
    )
    fake_redis.set(sc._entry_key(scope, entry_id), payload)
    fake_redis.sadd(sc._idx_key(scope), entry_id)

    state = make_initial_state("t1", "u1", "s1", "what is python")
    state["selected_model"] = "m1"
    state["intent"] = "qa"
    assert sc.lookup(state) is None
