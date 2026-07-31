"""LangFuse 客户端 — 可观测性 SDK"""

from __future__ import annotations

import os

_lf = None


def get_langfuse():
    """获取 LangFuse 单例 — LangFuse 不可用时返回 None"""
    global _lf
    if _lf is not None:
        return _lf

    host = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "pk-local-dev")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "sk-local-dev")

    # 未配置真实 key 时静默降级
    if not public_key or public_key == "pk-local-dev":
        return None

    try:
        from langfuse import Langfuse

        _lf = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        return _lf
    except Exception:
        return None
