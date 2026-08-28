"""In-process cancel registry for chat streaming runs (Task 63 slice 3)."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_active: set[str] = set()
_cancelled: set[str] = set()


class RunCancelledError(Exception):
    """Raised when a trace_id has been cancelled by the client."""


def register_run(trace_id: str) -> None:
    tid = (trace_id or "").strip()
    if not tid:
        return
    with _lock:
        _active.add(tid)
        _cancelled.discard(tid)


def unregister_run(trace_id: str) -> None:
    tid = (trace_id or "").strip()
    if not tid:
        return
    with _lock:
        _active.discard(tid)


def clear_cancel(trace_id: str) -> None:
    tid = (trace_id or "").strip()
    if not tid:
        return
    with _lock:
        _cancelled.discard(tid)


def request_cancel(trace_id: str) -> bool:
    """Mark trace cancelled. Returns True if run was active or already cancelled."""
    tid = (trace_id or "").strip()
    if not tid:
        return False
    with _lock:
        if tid not in _active and tid not in _cancelled:
            return False
        _cancelled.add(tid)
        return True


def is_cancelled(trace_id: str) -> bool:
    tid = (trace_id or "").strip()
    if not tid:
        return False
    with _lock:
        return tid in _cancelled


def check_cancelled(trace_id: str) -> None:
    if is_cancelled(trace_id):
        raise RunCancelledError(trace_id)
