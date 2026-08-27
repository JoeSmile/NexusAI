"""Embedding：租户凭证优先 + registry/env 回退；失败回退确定性哈希向量 (1536 维存储)。"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from typing import Literal

logger = logging.getLogger(__name__)

EMBED_DIM = 768  # pgvector 列维度（nomic-embed-text）；API 返回更短时补零

EmbedMode = Literal["api", "hash", "api-error", "cache", "unconfigured"]
_last_embed_mode: EmbedMode | None = None
_last_embed_model: str | None = None


def _set_embed_mode(mode: EmbedMode, model: str | None = None) -> None:
    global _last_embed_mode, _last_embed_model
    _last_embed_mode = mode
    if model is not None:
        _last_embed_model = model


def reset_embed_mode_for_tests() -> None:
    """测试用:清空上次调用结果缓存。"""
    global _last_embed_mode, _last_embed_model
    _last_embed_mode = None
    _last_embed_model = None


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


class _EmbedEndpoint:
    __slots__ = ("model", "api_key", "base_url", "dimensions", "source")

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        dimensions: int,
        source: str,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.dimensions = dimensions
        self.source = source


def _resolve_tenant_embedding(tenant_id: str) -> _EmbedEndpoint | None:
    from backend.core.errors import NexusAIException
    from backend.core.llm_credentials import (
        EMBEDDING_DIMENSIONS,
        resolve_embedding_credential_sync,
    )

    try:
        key, model = resolve_embedding_credential_sync(tenant_id)
    except NexusAIException:
        return None
    return _EmbedEndpoint(
        model=model,
        api_key=key.api_key,
        base_url=(key.base_url or "").rstrip("/"),
        dimensions=EMBEDDING_DIMENSIONS,
        source="tenant",
    )


def _resolve_registry_embedding() -> _EmbedEndpoint:
    """返回 registry/env 端点（无租户凭证时）。"""
    from backend.core.model_registry import select_embedding_model

    spec = select_embedding_model()
    base_url = (
        spec.base_url
        or os.getenv("EMBEDDING_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or ""
    ).rstrip("/")
    api_key = _resolve_api_key(spec.api_key_ref, base_url)
    dims = int(os.getenv("EMBEDDING_DIMENSIONS", "768") or "768")
    return _EmbedEndpoint(
        model=spec.name,
        api_key=api_key,
        base_url=base_url,
        dimensions=dims,
        source="registry",
    )


def _resolve_embedding_endpoint(tenant_id: str | None = None) -> _EmbedEndpoint:
    """解析顺序：租户 Embedding 凭证 → registry/env（保持旧行为，避免无凭证租户检索静默废掉）。"""
    if tenant_id:
        tenant_ep = _resolve_tenant_embedding(tenant_id)
        if tenant_ep is not None:
            return tenant_ep
        logger.debug(
            "tenant=%s 未配置 embedding 凭证，回退 registry/env",
            tenant_id,
        )
    return _resolve_registry_embedding()


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
        return qwen

    if qwen:
        return qwen
    return os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""


def embedding_uses_hash_fallback(tenant_id: str | None = None) -> bool:
    """True = 当前配置不足以打真实 embedding API(缺 key/url)。"""
    ep = _resolve_embedding_endpoint(tenant_id)
    return not (ep.api_key and ep.base_url)


def embedding_model_label(tenant_id: str | None = None) -> str:
    """供 /status、get_stats:反映配置 + 最近一次 embed 结果。"""
    name = _last_embed_model
    if not name:
        name = _resolve_embedding_endpoint(tenant_id).model
    mode = _last_embed_mode
    if mode is None:
        if embedding_uses_hash_fallback(tenant_id):
            return f"{name}(hash)"
        return name
    if mode == "api":
        return name
    if mode == "api-error":
        return f"{name}(api-error)"
    if mode == "cache":
        return f"{name}(cache)"
    return f"{name}(hash)"


def embed_text(text: str, tenant_id: str | None = None) -> list[float]:
    """生成 embedding。优先租户 Embedding 凭证；未配置则回退 registry/env；再失败才哈希兜底。

    L2 缓存(Task 29):归一化文本 → redis `rag:e:{model}:{hash}`;命中补零到 1536。
    """
    from backend.modules.rag.cache import (
        get_redis,
        l2_get,
        l2_set,
        normalize,
        record_l2_miss,
    )

    norm = normalize(text or "")
    ep = _resolve_embedding_endpoint(tenant_id)
    dims = ep.dimensions

    cached = l2_get(ep.model, norm)
    if cached is not None:
        _set_embed_mode("cache", ep.model)
        return _pad_or_trim(cached)

    if not ep.api_key or not ep.base_url:
        logger.debug(
            "未配置 embedding API key/base_url（source=%s），使用哈希 embedding",
            ep.source,
        )
        _set_embed_mode("unconfigured", ep.model)
        return _hash_embed(norm)

    if get_redis() is not None:
        record_l2_miss()
    from backend.core.errors import NexusAIException
    from backend.core.llm_concurrency import embed_http_timeout_s, embed_slot_sync

    try:
        from openai import OpenAI

        with embed_slot_sync(base_url=ep.base_url):
            client = OpenAI(
                api_key=ep.api_key,
                base_url=ep.base_url,
                timeout=embed_http_timeout_s(),
            )
            try:
                resp = client.embeddings.create(
                    model=ep.model,
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
                        model=ep.model,
                        input=norm[:8000],
                    )
                else:
                    raise
            vec = list(resp.data[0].embedding)
            _set_embed_mode("api", ep.model)
            try:
                l2_set(ep.model, norm, vec)
            except Exception:
                pass
            return _pad_or_trim(vec)
    except NexusAIException:
        raise
    except Exception as e:
        logger.warning("API embedding 失败，回退哈希向量（非语义）: %s", e)
        _set_embed_mode("api-error", ep.model)
        return _hash_embed(norm)
