"""MCP concurrency limits (Task 66 slice 3 / Phase 2)."""

from __future__ import annotations

import asyncio
import os

from packages.capability.exec_policy import global_default_exec_policy

_stdio_sem: asyncio.Semaphore | None = None
_call_sem: asyncio.Semaphore | None = None


def _max_stdio_spawn() -> int:
    policy = global_default_exec_policy()
    raw = os.getenv("CAPABILITY_MCP_MAX_GLOBAL_CONCURRENCY", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return max(1, policy.max_concurrent_mcp_subprocess)


def _max_calls() -> int:
    raw = os.getenv("CAPABILITY_MCP_MAX_CALL_CONCURRENCY", "16").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 16


def stdio_spawn_semaphore() -> asyncio.Semaphore:
    global _stdio_sem
    limit = _max_stdio_spawn()
    if _stdio_sem is None:
        _stdio_sem = asyncio.Semaphore(limit)
    return _stdio_sem


def mcp_call_semaphore() -> asyncio.Semaphore:
    global _call_sem
    if _call_sem is None:
        _call_sem = asyncio.Semaphore(_max_calls())
    return _call_sem


def reset_mcp_semaphores_for_tests() -> None:
    """Test helper — recreate semaphores after env changes."""
    global _stdio_sem, _call_sem
    _stdio_sem = None
    _call_sem = None


def stdio_spawn_limit() -> int:
    return _max_stdio_spawn()
