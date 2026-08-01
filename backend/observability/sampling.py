"""LangFuse 路径采样 — 短路径低采样、长路径全量。"""

from __future__ import annotations

import random
from contextvars import ContextVar

_tracing_enabled: ContextVar[bool] = ContextVar("langfuse_tracing_enabled", default=True)
_sample_decided: ContextVar[bool | None] = ContextVar(
    "langfuse_sample_decided", default=None
)

_SHORT_FINISH = frozenset(
    {
        "skill_executed",
        "cache_hit",
        "PENDING_APPROVAL",
        "rate_limited",
        "blocked",
        "AUTH_002",
    }
)


def is_short_path(finish_reason: str | None) -> bool:
    return (finish_reason or "") in _SHORT_FINISH


def sample_rate_for(finish_reason: str | None) -> float:
    from config import get_settings

    settings = get_settings()
    if is_short_path(finish_reason):
        return float(settings.langfuse_sample_short_path)
    return float(settings.langfuse_sample_long_path)


def should_sample(finish_reason: str | None) -> bool:
    """同一请求内只掷一次骰子；后续调用复用结果。"""
    decided = _sample_decided.get()
    if decided is not None:
        return decided
    rate = sample_rate_for(finish_reason)
    if rate >= 1.0:
        result = True
    elif rate <= 0.0:
        result = False
    else:
        result = random.random() < rate
    _sample_decided.set(result)
    return result


def set_tracing_enabled(enabled: bool) -> None:
    _tracing_enabled.set(enabled)


def tracing_enabled() -> bool:
    return bool(_tracing_enabled.get())


def reset_sampling_state(*, enabled: bool = True) -> None:
    """请求开始时重置采样状态。"""
    _tracing_enabled.set(enabled)
    _sample_decided.set(None)
