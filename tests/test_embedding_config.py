"""Task 28: embedding 模型选择与 embed_text(无真网络)"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _reload_registry(monkeypatch):
    """每个用例前后重置 registry 缓存与 embed 模式。"""
    import backend.core.model_registry as mr
    import backend.database.embeddings as emb
    from backend.modules.rag import cache as rag_cache

    # Task 29: 避免本地 redis-stack 污染 L2 命中,导致 API mock 未被调用
    monkeypatch.setenv("RAG_CACHE_ENABLED", "false")
    rag_cache.reset_redis_for_tests()

    mr.reload_registry()
    emb.reset_embed_mode_for_tests()
    yield
    mr.reload_registry()
    emb.reset_embed_mode_for_tests()
    rag_cache.reset_redis_for_tests()


def test_select_embedding_model_from_registry(monkeypatch):
    import backend.core.model_registry as mr

    monkeypatch.setenv(
        "MODEL_REGISTRY_JSON",
        '[{"name":"text-embedding-v3","provider":"qwen",'
        '"base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1",'
        '"api_key_ref":"QWEN_API_KEY","capability":"embedding",'
        '"tier":"cheap","cost_per_1k":0.0001,"max_tokens":0}]',
    )
    mr.reload_registry()
    spec = mr.select_embedding_model()
    assert spec.capability == "embedding"
    assert spec.name == "text-embedding-v3"
    assert "dashscope" in spec.base_url
    assert spec.api_key_ref == "QWEN_API_KEY"


def test_select_embedding_model_env_fallback(monkeypatch):
    import backend.core.model_registry as mr

    monkeypatch.setenv("MODEL_REGISTRY_JSON", "[]")
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    try:
        import config as cfg

        monkeypatch.setattr(
            cfg, "get_settings", lambda: SimpleNamespace(model_registry_json="")
        )
    except Exception:
        pass

    mr.reload_registry()
    spec = mr.select_embedding_model()
    assert spec.name == "text-embedding-v3"
    assert spec.capability == "embedding"
    assert "dashscope.aliyuncs.com" in spec.base_url
    assert spec.api_key_ref == "QWEN_API_KEY"


def test_embed_text_calls_api_with_dimensions(monkeypatch):
    import backend.core.model_registry as mr
    import backend.database.embeddings as emb

    monkeypatch.setenv(
        "MODEL_REGISTRY_JSON",
        '[{"name":"text-embedding-v3","provider":"qwen",'
        '"base_url":"https://dashscope.example/v1",'
        '"api_key_ref":"QWEN_API_KEY","capability":"embedding",'
        '"cost_per_1k":0.0001}]',
    )
    monkeypatch.setenv("QWEN_API_KEY", "sk-test")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    mr.reload_registry()

    created: dict = {}
    client_kwargs: dict = {}

    class _Resp:
        data = [SimpleNamespace(embedding=[0.1] * 768)]

    class _Embeddings:
        def create(self, **kwargs):
            created.update(kwargs)
            return _Resp()

    class _Client:
        def __init__(self, **k):
            client_kwargs.update(k)
            self.embeddings = _Embeddings()

    monkeypatch.setattr("openai.OpenAI", _Client)

    vec = emb.embed_text("你好 ContextGate")
    assert created["model"] == "text-embedding-v3"
    assert created["dimensions"] == 768
    assert client_kwargs.get("api_key") == "sk-test"
    assert "dashscope.example" in str(client_kwargs.get("base_url") or "")
    assert len(vec) == emb.EMBED_DIM
    assert vec[768:] == [0.0] * (emb.EMBED_DIM - 768)
    assert emb.embedding_model_label() == "text-embedding-v3"


def test_embed_text_retries_without_dimensions(monkeypatch):
    import backend.core.model_registry as mr
    import backend.database.embeddings as emb

    monkeypatch.setenv(
        "MODEL_REGISTRY_JSON",
        '[{"name":"text-embedding-v3","provider":"qwen",'
        '"base_url":"https://dashscope.example/v1",'
        '"api_key_ref":"QWEN_API_KEY","capability":"embedding"}]',
    )
    monkeypatch.setenv("QWEN_API_KEY", "sk-test")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    mr.reload_registry()

    calls: list[dict] = []

    class _Resp:
        data = [SimpleNamespace(embedding=[0.2] * 512)]

    class _Embeddings:
        def create(self, **kwargs):
            calls.append(dict(kwargs))
            if "dimensions" in kwargs:
                raise ValueError("dimensions parameter is not supported")
            return _Resp()

    class _Client:
        def __init__(self, *a, **k):
            self.embeddings = _Embeddings()

    monkeypatch.setattr("openai.OpenAI", _Client)

    vec = emb.embed_text("retry path")
    assert len(calls) == 2
    assert "dimensions" in calls[0]
    assert "dimensions" not in calls[1]
    assert len(vec) == emb.EMBED_DIM


def test_embed_text_hash_fallback_deterministic(monkeypatch):
    import backend.database.embeddings as emb

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

    import backend.core.model_registry as mr

    mr.reload_registry()
    a = emb.embed_text("同一段文本")
    b = emb.embed_text("同一段文本")
    assert len(a) == emb.EMBED_DIM
    assert a == b
    assert emb.embedding_uses_hash_fallback() is True
    assert emb.embedding_model_label().endswith("(hash)")


def test_api_error_label_shows_api_error(monkeypatch):
    """Important #1: API 失败后 status 不得假装真实 embedding。"""
    import backend.core.model_registry as mr
    import backend.database.embeddings as emb

    monkeypatch.setenv(
        "MODEL_REGISTRY_JSON",
        '[{"name":"text-embedding-v3","provider":"qwen",'
        '"base_url":"https://dashscope.example/v1",'
        '"api_key_ref":"QWEN_API_KEY","capability":"embedding"}]',
    )
    monkeypatch.setenv("QWEN_API_KEY", "sk-bad")
    mr.reload_registry()

    class _Embeddings:
        def create(self, **kwargs):
            raise RuntimeError("401 invalid api key")

    class _Client:
        def __init__(self, *a, **k):
            self.embeddings = _Embeddings()

    monkeypatch.setattr("openai.OpenAI", _Client)

    vec = emb.embed_text("fail")
    assert len(vec) == emb.EMBED_DIM
    assert emb.embedding_model_label() == "text-embedding-v3(api-error)"


def test_dashscope_ignores_llm_api_key_alone(monkeypatch):
    """Important #2: 仅有 DeepSeek LLM_API_KEY 时不应对 DashScope 发起假调用。"""
    import backend.core.model_registry as mr
    import backend.database.embeddings as emb

    monkeypatch.setenv(
        "MODEL_REGISTRY_JSON",
        '[{"name":"text-embedding-v3","provider":"qwen",'
        '"base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1",'
        '"api_key_ref":"QWEN_API_KEY","capability":"embedding"}]',
    )
    monkeypatch.setenv("LLM_API_KEY", "sk-deepseek-only")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    mr.reload_registry()

    called = {"n": 0}

    class _Client:
        def __init__(self, *a, **k):
            called["n"] += 1

    monkeypatch.setattr("openai.OpenAI", _Client)

    emb.embed_text("no qwen key")
    assert called["n"] == 0
    assert emb.embedding_uses_hash_fallback() is True
    assert emb.embedding_model_label().endswith("(hash)")
