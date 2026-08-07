"""LangFuse 客户端 — SDK v4（OTel-native）。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_lf: Any | None = None
_init_attempted = False

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
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY", "").strip())


def _base_url() -> str:
    # SDK v4 官方名 LANGFUSE_BASE_URL；兼容旧 LANGFUSE_HOST
    return (
        os.getenv("LANGFUSE_BASE_URL")
        or os.getenv("LANGFUSE_HOST")
        or "http://localhost:3001"
    ).rstrip("/")


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

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    if not public_key or not secret_key:
        return None

    # 同步给 SDK 默认读取的 BASE_URL
    os.environ.setdefault("LANGFUSE_BASE_URL", _base_url())
    os.environ.setdefault("LANGFUSE_HOST", _base_url())

    try:
        from langfuse import Langfuse

        _lf = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=_base_url(),
            host=_base_url(),
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


def discard_langfuse_buffer() -> None:
    """丢弃未 flush 的缓冲（短路径未命中采样时用）。"""
    global _lf, _init_attempted
    client = _lf
    _lf = None
    _init_attempted = False
    if client is None:
        return
    try:
        # v4: shutdown 停止导出；flush=False 尽量不发送
        if hasattr(client, "shutdown"):
            client.shutdown()
            return
    except Exception:
        pass
    try:
        del client
    except Exception:
        pass
