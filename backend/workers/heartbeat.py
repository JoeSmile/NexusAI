"""Deprecated shim — use ``apps.memory_worker.heartbeat`` (Task 75.5)."""

from __future__ import annotations

import warnings

warnings.warn(
    "backend.workers.heartbeat is deprecated; use apps.memory_worker.heartbeat",
    DeprecationWarning,
    stacklevel=2,
)

from apps.memory_worker.heartbeat import *  # noqa: F401,F403
