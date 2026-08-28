"""Deprecated shim — use ``apps.memory_worker`` (Task 75.5).

Keeps ``python -m backend.workers.memory_worker`` working for compose.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "backend.workers.memory_worker is deprecated; use apps.memory_worker",
    DeprecationWarning,
    stacklevel=2,
)

from apps.memory_worker.worker import *  # noqa: F401,F403
from apps.memory_worker.worker import run_forever

if __name__ == "__main__":
    run_forever()
