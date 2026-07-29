"""本地/兼容 embedding：优先 OpenAI 兼容 API，否则确定性哈希向量 (1536维)。"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from typing import List

logger = logging.getLogger(__name__)

EMBED_DIM = 1536


def _hash_embed(text: str, dim: int = EMBED_DIM) -> List[float]:
    """无外部模型时的确定性伪 embedding（仅保证同文同向量，非语义质量）。"""
    vec = [0.0] * dim
    if not text:
        return vec
    tokens = text.lower().split()
    if not tokens:
        tokens = [text]
    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        for i in range(0, min(len(digest), 32)):
            idx = (digest[i] + i * 17) % dim
            vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed_text(text: str) -> List[float]:
    """生成 embedding 向量。无 API 时回退哈希向量（仅开发/联通，非语义质量）。"""
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
    model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    if api_key and base_url:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=base_url)
            resp = client.embeddings.create(model=model, input=text[:8000])
            vec = list(resp.data[0].embedding)
            if len(vec) < EMBED_DIM:
                vec = vec + [0.0] * (EMBED_DIM - len(vec))
            return vec[:EMBED_DIM]
        except Exception as e:
            logger.warning("API embedding 失败，回退哈希向量（非语义）: %s", e)
    else:
        logger.debug("未配置 LLM_API_KEY，使用哈希 embedding（非语义，仅本地联通）")

    return _hash_embed(text)
