"""Task 82.3: RAG ingest refuses hash-fallback embeddings."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from packages.errors import ErrorCode, NexusAIException


def test_add_knowledge_refuses_hash_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import packages.database.vector_ops as vo

    monkeypatch.setattr(
        vo, "embedding_uses_hash_fallback", lambda tenant_id=None: True, raising=False
    )
    monkeypatch.setattr(vo, "embed_text", lambda *a, **k: [0.0] * 1024)

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def add(self, row):
            row.id = 1

        def commit(self):
            return None

    monkeypatch.setattr(
        vo, "get_pg_session", lambda: MagicMock(Session=lambda: _Session())
    )

    with pytest.raises(NexusAIException) as ei:
        vo.add_knowledge("chunk text", tenant_id="acme")
    assert ei.value.code == ErrorCode.EMBED_UNAVAILABLE.value


def test_add_knowledge_embeds_when_api_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    import packages.database.vector_ops as vo

    monkeypatch.setattr(
        vo, "embedding_uses_hash_fallback", lambda tenant_id=None: False, raising=False
    )

    def _ok_embed(*_a, **_k):
        import packages.database.embeddings as emb

        emb._set_embed_mode("api", "m")
        return [0.1] * 1024

    monkeypatch.setattr(vo, "embed_text", _ok_embed)

    added: list[object] = []

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def add(self, row):
            added.append(row)
            row.id = 7

        def commit(self):
            return None

    monkeypatch.setattr(
        vo, "get_pg_session", lambda: MagicMock(Session=lambda: _Session())
    )
    kid = vo.add_knowledge("ok chunk", tenant_id="acme")
    assert kid == 7
    assert len(added) == 1
    assert len(added[0].embedding) == 1024


def test_add_knowledge_refuses_api_error_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    import packages.database.embeddings as emb
    import packages.database.vector_ops as vo

    monkeypatch.setattr(
        vo, "embedding_uses_hash_fallback", lambda tenant_id=None: False, raising=False
    )

    def _embed(*_a, **_k):
        emb._set_embed_mode("api-error", "m")
        return [0.0] * 1024

    monkeypatch.setattr(vo, "embed_text", _embed)

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def add(self, row):
            row.id = 1

        def commit(self):
            return None

    monkeypatch.setattr(
        vo, "get_pg_session", lambda: MagicMock(Session=lambda: _Session())
    )
    with pytest.raises(NexusAIException) as ei:
        vo.add_knowledge("chunk text", tenant_id="acme")
    assert ei.value.code == ErrorCode.EMBED_UNAVAILABLE.value
