"""Embedding：registry 选模型 + OpenAI 兼容 API；失败回退确定性哈希向量 (1536 维存储)。"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from typing import Literal

logger = logging.getLogger(__name__)

EMBED_DIM = 1536  # pgvector 列维度；API 返回更短时补零

EmbedMode = Literal["api", "hash", "api-error", "cache", "unconfigured"]
_last_embed_mode: EmbedMode | None = None


def _set_embed_mode(mode: EmbedMode) -> None:
    global _last_embed_mode
    _last_embed_mode = mode


def reset_embed_mode_for_tests() -> None:
    """测试用:清空上次调用结果缓存。"""
    global _last_embed_mode
    _last_embed_mode = None


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
    """供应商不接受 dimensions 参数时的启发式。"""
    msg = str(exc).lower()
    return "dimension" in msg or "dimensions" in msg


def _pad_or_trim(vec: list[float]) -> list[float]:
    if len(vec) < EMBED_DIM:
        return vec + [0.0] * (EMBED_DIM - len(vec))
    return vec[:EMBED_DIM]


def _is_dashscope_url(base_url: str) -> bool:
    u = (base_url or "").lower()
    return "dashscope" in u or "aliyuncs" in u


def _resolve_embedding_endpoint() -> tuple[object, str, str]:
    """返回 (spec, api_key, base_url)。"""
    from backend.core.model_registry import select_embedding_model

    spec = select_embedding_model()
    base_url = (
        spec.base_url
        or os.getenv("EMBEDDING_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or ""
    ).rstrip("/")
    api_key = _resolve_api_key(spec.api_key_ref, base_url)
    return spec, api_key, base_url


def _resolve_api_key(api_key_ref: str, base_url: str = "") -> str:
    """按 endpoint 解析 key:DashScope 不用 DeepSeek/OpenAI 的 LLM_API_KEY 冒充。"""
    if os.getenv("EMBEDDING_API_KEY"):
        return os.getenv("EMBEDDING_API_KEY") or ""

    if api_key_ref:
        ref_val = os.getenv(api_key_ref) or ""
        if ref_val:
            return ref_val

    qwen = os.getenv("QWEN_API_KEY") or ""
    if _is_dashscope_url(base_url):
        # Task 28 review Important #2: 禁止用 deepseek LLM_API_KEY 打 dashscope
        return qwen

    if qwen:
        return qwen
    return os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""


def embedding_uses_hash_fallback() -> bool:
    """True = 当前配置不足以打真实 embedding API(缺 key/url)。"""
    _spec, api_key, base_url = _resolve_embedding_endpoint()
    return not (api_key and base_url)


def embedding_model_label() -> str:
    """供 /status、get_stats:反映配置 + 最近一次 embed 结果。"""
    from backend.core.model_registry import select_embedding_model

    name = select_embedding_model().name
    mode = _last_embed_mode
    if mode is None:
        if embedding_uses_hash_fallback():
            return f"{name}(hash)"
        return name
    if mode == "api":
        return name
    if mode == "api-error":
        return f"{name}(api-error)"
    if mode == "cache":
        return f"{name}(cache)"
    # hash / unconfigured
    return f"{name}(hash)"


def embed_text(text: str) -> list[float]:
    """生成 embedding。优先 registry embedding 模型;无 key/失败则哈希兜底。

    L2 缓存(Task 29):归一化文本 → redis `rag:e:{model}:{hash}`;命中补零到 1536。
    """
    from backend.modules.rag.cache import (
        get_redis,
        l2_get,
        l2_set,
        normalize,
        record_l2_miss,
    )

    # 与 L1/L2 key 一致:归一化后文本作为 embed 输入
    norm = normalize(text or "")
    spec, api_key, base_url = _resolve_embedding_endpoint()
    dims = int(os.getenv("EMBEDDING_DIMENSIONS", "768") or "768")

    cached = l2_get(spec.name, norm)
    if cached is not None:
        _set_embed_mode("cache")  # L2 命中:非真实 API 调用(仅此前已成功过)
        return _pad_or_trim(cached)

    if not api_key or not base_url:
        logger.debug(
            "未配置 embedding API key/base_url，使用哈希 embedding（非语义，仅本地联通）"
        )
        _set_embed_mode("unconfigured")
        return _hash_embed(norm)

    if get_redis() is not None:
        record_l2_miss()
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)
        try:
            resp = client.embeddings.create(
                model=spec.name,
                input=norm[:8000],
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
                    input=norm[:8000],
                )
            else:
                raise
        vec = list(resp.data[0].embedding)
        _set_embed_mode("api")
        try:
            l2_set(spec.name, norm, vec)
        except Exception:
            pass
        return _pad_or_trim(vec)
    except Exception as e:
        logger.warning("API embedding 失败，回退哈希向量（非语义）: %s", e)
        _set_embed_mode("api-error")
        return _hash_embed(norm)
