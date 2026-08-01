"""可观测装饰器 — LangFuse SDK 可用则埋点，否则 no-op。

注意：装饰发生在 import 时，因此这里不做 LANGFUSE_ENABLED 门控
（避免 dotenv 尚未加载时把节点永久装饰成空操作）。开关由
langfuse_client / 环境变量在运行时控制 SDK 行为。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

try:
    from langfuse.decorators import langfuse_context as langfuse_context
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

    langfuse_context = _NoopContext()  # type: ignore[misc]


def observe(*args: Any, **kwargs: Any):
    """兼容 `@observe` / `@observe(name=...)` / `@observe(name=..., as_type=...)`"""
    return _lf_observe(*args, **kwargs)


__all__ = ["langfuse_context", "observe"]
