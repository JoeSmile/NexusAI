"""Deprecated shim — use ``packages.intent`` (Task 75 / Phase 1 pilot).

Kept for one Wave so leftover imports do not crash.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "backend.modules.intent is deprecated; import from packages.intent",
    DeprecationWarning,
    stacklevel=2,
)

from packages.intent import *  # noqa: F401,F403
