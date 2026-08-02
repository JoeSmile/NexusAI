"""Embedding：registry 选模型 + OpenAI 兼容 API；失败回退确定性哈希向量 (1536 维存储)。"""

from __future__ import annotations

import hashlib
import logging
import math
import os

logger = logging.getLogger(__name__)

EMBED_DIM = 1536  # pgvector 列维度；API 返回更短时补零


def _hash_embed(text: str, dim: int = EMBED_DIM) -> list[float]:
    """无外部模型时的确定性伪 embedding（仅保证同文同向量，非语义质量）。"""
    vec = [0.0] * dim
    if not text:
        return vec
    tokens = text.lower().split()
    if not tokens:
        tokens = [text]
    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        for i in range(min(len(digest), 32)):
            idx = (digest[i] + i * 17) % dim
            vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _dimensions_unsupported(exc: BaseException) -> bool:
    """供应商不接受 dimensions 参数时的启发式(不用做字符串精确匹配业务错误)。"""
    msg = str(exc).lower()
    return "dimension" in msg or "dimensions" in msg


def _pad_or_trim(vec: list[float]) -> list[float]:
    if len(vec) < EMBED_DIM:
        return vec + [0.0] * (EMBED_DIM - len(vec))
    return vec[:EMBED_DIM]


def _resolve_api_key(api_key_ref: str) -> str:
    return (
        os.getenv("EMBEDDING_API_KEY")
        or (os.getenv(api_key_ref) if api_key_ref else "")
        or os.getenv("QWEN_API_KEY")
        or os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )


def embedding_uses_hash_fallback() -> bool:
    """供 status/stats 展示:当前是否会因缺 key/url 走哈希。"""
    from backend.core.model_registry import select_embedding_model

    spec = select_embedding_model()
    api_key = _resolve_api_key(spec.api_key_ref)
    base_url = (
        spec.base_url
        or os.getenv("EMBEDDING_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or ""
    ).rstrip("/")
    return not (api_key and base_url)


def embed_text(text: str) -> list[float]:
    """生成 embedding。优先 registry embedding 模型;无 key/失败则哈希兜底。"""
    from backend.core.model_registry import select_embedding_model

    spec = select_embedding_model()
    api_key = _resolve_api_key(spec.api_key_ref)
    base_url = (
        spec.base_url
        or os.getenv("EMBEDDING_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or ""
    ).rstrip("/")
    dims = int(os.getenv("EMBEDDING_DIMENSIONS", "768") or "768")

    if not api_key or not base_url:
        logger.debug(
            "未配置 embedding API key/base_url，使用哈希 embedding（非语义，仅本地联通）"
        )
        return _hash_embed(text)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)
        try:
            resp = client.embeddings.create(
                model=spec.name,
                input=text[:8000],
                dimensions=dims,
            )
        except Exception as e:
            if _dimensions_unsupported(e):
                logger.info(
                    "embedding dimensions=%s 不被支持，重试不带 dimensions: %s",
                    dims,
                    e,
                )
                resp = client.embeddings.create(
                    model=spec.name,
                    input=text[:8000],
                )
            else:
                raise
        vec = list(resp.data[0].embedding)
        return _pad_or_trim(vec)
    except Exception as e:
        logger.warning("API embedding 失败，回退哈希向量（非语义）: %s", e)
        return _hash_embed(text)
