"""Prompt-side token estimates (S2). Billing/quota stay on cost_manager / token_quota."""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

TRIM_BUDGET_RATIO = 0.85

_lock = threading.Lock()
_encoder: Any = None  # None unloaded; False failed; else tiktoken Encoding


def reset_for_tests() -> None:
    global _encoder
    with _lock:
        _encoder = None


def fallback_estimate_tokens(text: str) -> int:
    """汉字 ×1 + 其他 ÷4。tiktoken 不可用时的回退。"""
    han = 0
    other = 0
    for ch in text or "":
        if "\u4e00" <= ch <= "\u9fff":
            han += 1
        else:
            other += 1
    return max(1, han + other // 4)


def _load_encoder() -> Any:
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        logger.warning(
            "tiktoken cl100k_base unavailable; falling back to CJK×1 + other÷4"
        )
        return None


def _get_encoder() -> Any:
    global _encoder
    if _encoder is False:
        return None
    if _encoder is not None:
        return _encoder
    with _lock:
        if _encoder is False:
            return None
        if _encoder is not None:
            return _encoder
        enc = _load_encoder()
        _encoder = enc if enc is not None else False
        return enc


def estimate_tokens(text: str | None) -> int:
    raw = text or ""
    if not raw:
        return 1
    enc = _get_encoder()
    if enc is None:
        return fallback_estimate_tokens(raw)
    try:
        n = len(enc.encode(raw, disallowed_special=()))
        return max(1, n)
    except Exception:
        logger.warning("tiktoken encode failed; using fallback", exc_info=True)
        return fallback_estimate_tokens(raw)


def trim_token_budget(budget: int) -> int:
    return max(1, int(budget * TRIM_BUDGET_RATIO))
