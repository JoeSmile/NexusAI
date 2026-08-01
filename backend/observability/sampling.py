"""LangFuse 路径采样 — 短路径低采样、长路径全量。"""

from __future__ import annotations

import random
from contextvars import ContextVar

_tracing_enabled: ContextVar[bool] = ContextVar("langfuse_tracing_enabled", default=True)

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
    rate = sample_rate_for(finish_reason)
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    return random.random() < rate


def set_tracing_enabled(enabled: bool) -> None:
    _tracing_enabled.set(enabled)


def tracing_enabled() -> bool:
    return bool(_tracing_enabled.get())
