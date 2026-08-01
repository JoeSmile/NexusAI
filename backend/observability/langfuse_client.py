"""LangFuse 客户端 — 可观测性 SDK"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_lf: Any | None = None
_init_attempted = False

# 保证即便未经过 app.py 也能读到 config.env
try:
    from dotenv import load_dotenv

    _root = Path(__file__).resolve().parents[2]
    load_dotenv(_root / "config.env")
except Exception:
    pass


def _truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def langfuse_enabled() -> bool:
    """默认开启；设 LANGFUSE_ENABLED=0 可显式关闭。"""
    if "LANGFUSE_ENABLED" in os.environ:
        return _truthy("LANGFUSE_ENABLED")
    # 有 public key 即视为启用（含本地 init key）
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY", "").strip())


def get_langfuse():
    """获取 LangFuse 单例；未启用或初始化失败时返回 None。"""
    global _lf, _init_attempted
    if _lf is not None:
        return _lf
    if _init_attempted:
        return None
    _init_attempted = True

    if not langfuse_enabled():
        return None

    host = os.getenv("LANGFUSE_HOST", "http://localhost:3001").rstrip("/")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    if not public_key or not secret_key:
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
        _lf = None
        return None


def flush_langfuse() -> None:
    """尽量把缓冲中的 trace 刷到 LangFuse（请求结束时调用）。"""
    client = get_langfuse()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        pass
