"""Task 28: embedding 模型选择与 embed_text(无真网络)"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _reload_registry():
    """每个用例前后重置 registry 缓存。"""
    import backend.core.model_registry as mr

    mr.reload_registry()
    yield
    mr.reload_registry()


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
    # 清空 settings 缓存侧可能带的 registry
    monkeypatch.setattr(
        "backend.core.model_registry.get_settings",
        lambda: SimpleNamespace(model_registry_json=""),
        raising=False,
    )
    # _default_models 读 get_settings — patch config.get_settings
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

    class _Resp:
        data = [SimpleNamespace(embedding=[0.1] * 768)]

    class _Embeddings:
        def create(self, **kwargs):
            created.update(kwargs)
            return _Resp()

    class _Client:
        def __init__(self, *a, **k):
            self.embeddings = _Embeddings()

    monkeypatch.setattr("openai.OpenAI", _Client)

    vec = emb.embed_text("你好 ContextGate")
    assert created["model"] == "text-embedding-v3"
    assert created["dimensions"] == 768
    assert len(vec) == emb.EMBED_DIM
    assert vec[768:] == [0.0] * (emb.EMBED_DIM - 768)


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
    # 兜底 spec 仍有默认 base_url — 无 key 时应走哈希
    a = emb.embed_text("同一段文本")
    b = emb.embed_text("同一段文本")
    assert len(a) == emb.EMBED_DIM
    assert a == b
    assert emb.embedding_uses_hash_fallback() is True
