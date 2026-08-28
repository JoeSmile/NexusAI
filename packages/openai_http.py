"""Shared httpx clients for OpenAI-compatible SDK (Task 73 slice 6).

Per-request ``AsyncOpenAI()`` each owns a pool; passing Limits there multiplies
fds. One process-level client is the cap.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ASYNC: httpx.AsyncClient | None = None
_SYNC: httpx.Client | None = None

_LIMITS = httpx.Limits(max_connections=256, max_keepalive_connections=64)
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def openai_async_http_client() -> httpx.AsyncClient:
    global _ASYNC
    if _ASYNC is None or _ASYNC.is_closed:
        _ASYNC = httpx.AsyncClient(limits=_LIMITS, timeout=_TIMEOUT)
    return _ASYNC


def openai_sync_http_client() -> httpx.Client:
    global _SYNC
    if _SYNC is None or _SYNC.is_closed:
        _SYNC = httpx.Client(limits=_LIMITS, timeout=_TIMEOUT)
    return _SYNC


def openai_client_kwargs() -> dict[str, Any]:
    """Pass into ``AsyncOpenAI`` / ``OpenAI`` so the SDK does not own the pool."""
    return {"http_client": openai_async_http_client()}


def openai_sync_client_kwargs() -> dict[str, Any]:
    return {"http_client": openai_sync_http_client()}


async def aclose_openai_http_clients() -> None:
    global _ASYNC, _SYNC
    if _ASYNC is not None and not _ASYNC.is_closed:
        await _ASYNC.aclose()
    _ASYNC = None
    if _SYNC is not None and not _SYNC.is_closed:
        _SYNC.close()
    _SYNC = None
    logger.debug("openai shared http clients closed")
