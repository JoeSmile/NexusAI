"""可观测装饰器 — LangFuse SDK 可用则埋点，否则 no-op。

注意：装饰发生在 import 时，因此这里不做 LANGFUSE_ENABLED 门控
（避免 dotenv 尚未加载时把节点永久装饰成空操作）。开关由
langfuse_client / 环境变量在运行时控制 SDK 行为。
采样由 observability.sampling.tracing_enabled 控制（短路径可降采样）。
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

try:
    from langfuse.decorators import langfuse_context as _lf_context
    from langfuse.decorators import observe as _lf_observe
except ImportError:

    def _lf_observe(*args: Any, **kwargs: Any):  # type: ignore[misc]
        def _decorator(fn: F) -> F:
            return fn

        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return args[0]
        return _decorator

    class _NoopContext:
        def update_current_generation(self, **kwargs: Any) -> None:
            return None

        def update_current_observation(self, **kwargs: Any) -> None:
            return None

        def update_current_trace(self, **kwargs: Any) -> None:
            return None

        def get_current_trace_id(self) -> None:
            return None

        def get_current_observation_id(self) -> None:
            return None

    _lf_context = _NoopContext()  # type: ignore[misc]


langfuse_context = _lf_context


def observe(*args: Any, **kwargs: Any):
    """兼容 `@observe` / `@observe(name=...)`；叠加路径采样门控。"""

    def _apply(fn: F) -> F:
        decorated = _lf_observe(**kwargs)(fn) if kwargs else _lf_observe(fn)
        is_coro = asyncio.iscoroutinefunction(fn) or inspect.iscoroutinefunction(fn)
        is_agen = inspect.isasyncgenfunction(fn)

        if is_coro:

            @functools.wraps(fn)
            async def _async_wrapper(*a: Any, **kw: Any) -> Any:
                from backend.observability.sampling import tracing_enabled

                if not tracing_enabled():
                    return await fn(*a, **kw)
                return await decorated(*a, **kw)

            return _async_wrapper  # type: ignore[return-value]

        if is_agen:
            # async gen: span 保持到 generator 耗尽（capability SSE 长路径）
            @functools.wraps(fn)
            def _agen_wrapper(*a: Any, **kw: Any) -> Any:
                from backend.observability.sampling import tracing_enabled

                if not tracing_enabled():
                    return fn(*a, **kw)
                return decorated(*a, **kw)

            return _agen_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def _sync_wrapper(*a: Any, **kw: Any) -> Any:
            from backend.observability.sampling import tracing_enabled

            if not tracing_enabled():
                return fn(*a, **kw)
            return decorated(*a, **kw)

        return _sync_wrapper  # type: ignore[return-value]

    if args and callable(args[0]) and len(args) == 1 and not kwargs:
        return _apply(args[0])
    return _apply


def enrich_span(
    *,
    input_data: Any = None,
    output_data: Any = None,
    metadata: dict[str, Any] | None = None,
    level: str | None = None,
) -> None:
    """加深当前 observation 的 IO / 元数据（采样关闭时 no-op）。"""
    from backend.observability.sampling import tracing_enabled

    if not tracing_enabled():
        return
    payload: dict[str, Any] = {}
    if input_data is not None:
        payload["input"] = _truncate(input_data)
    if output_data is not None:
        payload["output"] = _truncate(output_data)
    if metadata:
        payload["metadata"] = metadata
    if level:
        payload["level"] = level
    if not payload:
        return
    try:
        langfuse_context.update_current_observation(**payload)  # type: ignore[attr-defined]
    except Exception:
        try:
            langfuse_context.update_current_generation(**payload)  # type: ignore[attr-defined]
        except Exception:
            pass


def _truncate(value: Any, limit: int = 2000) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


__all__ = ["enrich_span", "langfuse_context", "observe"]
