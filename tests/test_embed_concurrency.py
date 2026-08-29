"""Task 73 slice 4 — embedding 独立槽：仅真实 HTTP 占槽。"""

from __future__ import annotations

import threading

import pytest

from packages.errors import ErrorCode, NexusAIException
from packages.llm_concurrency import (
    embed_slot_sync,
    embed_slots_in_flight,
    reset_llm_concurrency_for_tests,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EMBED_CONCURRENCY_LIMIT", "2")
    monkeypatch.setenv("EMBED_BUCKET_LIMIT", "1")
    monkeypatch.setenv("LLM_CONCURRENCY_ACQUIRE_TIMEOUT_S", "0.3")
    monkeypatch.setattr(
        "packages.redis_tools.get_ratelimit_sync_redis",
        lambda **_k: None,
    )
    reset_llm_concurrency_for_tests()
    yield
    reset_llm_concurrency_for_tests()


def test_embed_timeout_releases_slot() -> None:
    ready = threading.Event()
    release = threading.Event()

    def _hold() -> None:
        with embed_slot_sync(timeout_s=2.0, base_url="https://embed.example/v1"):
            ready.set()
            release.wait(timeout=2.0)

    t = threading.Thread(target=_hold)
    t.start()
    assert ready.wait(timeout=1.0)
    with pytest.raises(NexusAIException) as ei:
        with embed_slot_sync(timeout_s=0.12, base_url="https://embed.example/v1"):
            pass
    assert ei.value.code == ErrorCode.RATE_LIMITED.value
    release.set()
    t.join(timeout=2.0)
    assert embed_slots_in_flight() == 0
    with embed_slot_sync(timeout_s=0.3, base_url="https://embed.example/v1"):
        pass


def test_embed_buckets_by_base_url() -> None:
    ready = threading.Event()
    release = threading.Event()

    def _hold() -> None:
        with embed_slot_sync(timeout_s=2.0, base_url="https://a.embed.example/v1"):
            ready.set()
            release.wait(timeout=2.0)

    t = threading.Thread(target=_hold)
    t.start()
    assert ready.wait(timeout=1.0)
    with embed_slot_sync(timeout_s=0.4, base_url="https://b.embed.example/v1"):
        assert embed_slots_in_flight() == 2
    release.set()
    t.join(timeout=2.0)


def test_embed_hash_and_cache_skip_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    import packages.model_registry as mr
    import packages.database.embeddings as emb

    monkeypatch.setenv("RAG_CACHE_ENABLED", "false")
    for key in (
        "EMBEDDING_API_KEY",
        "QWEN_API_KEY",
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "EMBEDDING_BASE_URL",
        "LLM_BASE_URL",
        "MODEL_REGISTRY_JSON",
    ):
        monkeypatch.delenv(key, raising=False)
    mr.reload_registry()
    assert embed_slots_in_flight() == 0
    vec = emb.embed_text("hash path no slot")
    assert len(vec) == emb.EMBED_DIM
    assert embed_slots_in_flight() == 0


def test_embed_http_uses_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import packages.model_registry as mr
    import packages.database.embeddings as emb
    from packages.rag import cache as rag_cache

    monkeypatch.setenv("RAG_CACHE_ENABLED", "false")
    rag_cache.reset_redis_for_tests()
    monkeypatch.setenv(
        "MODEL_REGISTRY_JSON",
        '[{"name":"text-embedding-v3","provider":"qwen",'
        '"base_url":"https://dashscope.example/v1",'
        '"api_key_ref":"QWEN_API_KEY","capability":"embedding"}]',
    )
    monkeypatch.setenv("QWEN_API_KEY", "sk-test")
    mr.reload_registry()
    seen: list[int] = []

    class _Resp:
        data = [SimpleNamespace(embedding=[0.1] * 768)]

    class _Embeddings:
        def create(self, **kwargs):
            seen.append(embed_slots_in_flight())
            return _Resp()

    class _Client:
        def __init__(self, **k):
            self.embeddings = _Embeddings()

    monkeypatch.setattr("openai.OpenAI", _Client)
    emb.embed_text("real http")
    assert seen == [1]
    assert embed_slots_in_flight() == 0


def test_embed_cache_hit_skips_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    import packages.database.embeddings as emb

    monkeypatch.setattr(
        "packages.rag.cache.l2_get",
        lambda model, text: [0.3] * 768,
    )
    monkeypatch.setattr(
        "packages.database.embeddings._resolve_embedding_endpoint",
        lambda tenant_id=None: type(
            "E",
            (),
            {
                "model": "m",
                "api_key": "sk",
                "base_url": "https://x.example/v1",
                "dimensions": 768,
                "source": "t",
            },
        )(),
    )
    called = {"n": 0}

    class _Client:
        def __init__(self, **k):
            called["n"] += 1

    monkeypatch.setattr("openai.OpenAI", _Client)
    vec = emb.embed_text("cached")
    assert called["n"] == 0
    assert len(vec) == emb.EMBED_DIM
    assert embed_slots_in_flight() == 0
