"""Local vector index for tool metadata (Task 60)."""

from __future__ import annotations

import logging
import math
import os
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_EMBED_DIM = 384  # in-memory tool vectors (not pgvector storage)


def _hash_embed(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """Deterministic fallback when local model unavailable (CI / no model path)."""
    import hashlib

    vec = [0.0] * dim
    if not text:
        return vec
    for tok in text.lower().split():
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        for i in range(min(len(digest), 32)):
            idx = (digest[i] + i * 13) % dim
            vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class LocalToolEmbedder:
    """Lazy-load bge-small-zh via sentence-transformers; hash fallback otherwise."""

    def __init__(self) -> None:
        self._model: Any = None
        self._mode = "hash"
        self._load_attempted = False

    @property
    def mode(self) -> str:
        return self._mode

    def _ensure_model(self) -> None:
        if self._load_attempted:
            return
        self._load_attempted = True
        model_path = (
            os.getenv("TOOL_SEARCH_EMBED_MODEL")
            or os.getenv("TOOL_SEARCH_EMBED_MODEL_PATH")
            or "BAAI/bge-small-zh-v1.5"
        )
        try:
            from sentence_transformers import SentenceTransformer

            device = os.getenv("TOOL_SEARCH_EMBED_DEVICE", "cpu")
            self._model = SentenceTransformer(model_path, device=device)
            self._mode = "local"
            logger.info("tool_search embedder loaded: %s (%s)", model_path, device)
        except Exception as exc:
            logger.info(
                "tool_search embedder unavailable (%s); using hash fallback", exc
            )
            self._model = None
            self._mode = "hash"

    def embed(self, text: str) -> np.ndarray:
        self._ensure_model()
        norm = (text or "").strip()
        if not norm:
            return np.zeros(_EMBED_DIM, dtype=np.float32)
        if self._model is None:
            return np.asarray(_hash_embed(norm, _EMBED_DIM), dtype=np.float32)
        vec = self._model.encode(norm, normalize_embeddings=True)
        return np.asarray(vec, dtype=np.float32)


class VectorToolIndex:
    """Precomputed capability vectors keyed by id."""

    def __init__(self, embedder: LocalToolEmbedder | None = None) -> None:
        self._embedder = embedder or LocalToolEmbedder()
        self._vectors: dict[str, np.ndarray] = {}

    @property
    def embedder_mode(self) -> str:
        return self._embedder.mode

    def clear(self) -> None:
        self._vectors.clear()

    def upsert(self, doc_id: str, text: str) -> None:
        self._vectors[doc_id] = self._embedder.embed(text)

    def remove(self, doc_id: str) -> None:
        self._vectors.pop(doc_id, None)

    def search(self, query: str, *, top_k: int = 20) -> list[tuple[str, float]]:
        if not self._vectors:
            return []
        q = self._embedder.embed(query)
        if float(np.linalg.norm(q)) == 0.0:
            return []
        scores: list[tuple[str, float]] = []
        for doc_id, vec in self._vectors.items():
            if vec.shape != q.shape:
                continue
            sim = float(np.dot(q, vec))
            if sim > 0:
                scores.append((doc_id, sim))
        scores.sort(key=lambda x: (-x[1], x[0]))
        return scores[: max(1, top_k)]
