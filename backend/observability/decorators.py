"""可观测装饰器 — LangFuse SDK v4；不可用则 no-op。

注意：装饰发生在 import 时，因此这里不做 LANGFUSE_ENABLED 门控
（避免 dotenv 尚未加载时把节点永久装饰成空操作）。开关由
langfuse_client / 环境变量在运行时控制 SDK 行为。
采样由 observability.sampling.tracing_enabled 控制（短路径可降采样）。

v4 变更：``langfuse.decorators`` 已移除 → ``from langfuse import observe, get_client``。
本模块保留 ``langfuse_context`` 兼容面，供 router / harness / experiment_hook 调用。
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

try:
    from langfuse import observe as _lf_observe
except ImportError:

    def _lf_observe(*args: Any, **kwargs: Any):  # type: ignore[misc]
        def _decorator(fn: F) -> F:
            return fn

        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return args[0]
        return _decorator


class _LangfuseContextShim:
    """v2 ``langfuse_context`` API 的薄封装 → SDK v4 ``get_client()``。"""

    def _client(self) -> Any | None:
        try:
            from backend.observability.langfuse_client import get_langfuse

            return get_langfuse()
        except Exception:
            return None

    def update_current_observation(self, **kwargs: Any) -> None:
        client = self._client()
        if client is None:
            return
        payload = _normalize_observation_kwargs(kwargs)
        try:
            client.update_current_span(**payload)
        except Exception:
            try:
                client.update_current_generation(**payload)
            except Exception:
                pass

    def update_current_generation(self, **kwargs: Any) -> None:
        client = self._client()
        if client is None:
            return
        payload = _normalize_observation_kwargs(kwargs)
        try:
            client.update_current_generation(**payload)
        except Exception:
            try:
                client.update_current_span(**payload)
            except Exception:
                pass

    def update_current_trace(self, **kwargs: Any) -> None:
        """v4 无 span metadata / tags 近似；无独立 update_current_trace。"""
        client = self._client()
        if client is None:
            return
        meta = dict(kwargs.get("metadata") or {})
        tags = kwargs.get("tags")
        if tags:
            meta.setdefault("tags", tags)
        for key in ("user_id", "session_id", "name"):
            if key in kwargs and kwargs[key] is not None:
                meta.setdefault(key, kwargs[key])
        try:
            if meta:
                client.update_current_span(metadata=meta)
        except Exception:
            pass
        # IO 显式落在 trace 根上（若调用方传了 input/output）
        io_keys = {k: kwargs[k] for k in ("input", "output") if k in kwargs}
        if io_keys:
            try:
                client.set_current_trace_io(**io_keys)
            except Exception:
                pass

    def get_current_trace_id(self) -> str | None:
        client = self._client()
        if client is None:
            return None
        try:
            return client.get_current_trace_id()
        except Exception:
            return None

    def get_current_observation_id(self) -> str | None:
        client = self._client()
        if client is None:
            return None
        try:
            return client.get_current_observation_id()
        except Exception:
            return None


def _normalize_observation_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """v2 usage={input,output} → v4 usage_details。"""
    out = dict(kwargs)
    usage = out.pop("usage", None)
    if isinstance(usage, dict) and "usage_details" not in out:
        details: dict[str, int] = {}
        if "input" in usage:
            details["input"] = int(usage["input"] or 0)
        if "output" in usage:
            details["output"] = int(usage["output"] or 0)
        if "total" in usage:
            details["total"] = int(usage["total"] or 0)
        if details:
            out["usage_details"] = details
    return out


langfuse_context = _LangfuseContextShim()


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
        langfuse_context.update_current_observation(**payload)
    except Exception:
        try:
            langfuse_context.update_current_generation(**payload)
        except Exception:
            pass


def _truncate(value: Any, limit: int = 2000) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


__all__ = ["enrich_span", "langfuse_context", "observe"]
