"""Deprecated shim — use ``apps.social_worker`` (Task 75.5).

Keeps ``python -m backend.workers.social_worker`` working for compose.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "backend.workers.social_worker is deprecated; use apps.social_worker",
    DeprecationWarning,
    stacklevel=2,
)

from apps.social_worker.worker import *  # noqa: F401,F403
from apps.social_worker.worker import run_forever

if __name__ == "__main__":
    run_forever()
