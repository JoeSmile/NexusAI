"""Deprecated shim — use `packages.plan` (Task 75.4)."""
from __future__ import annotations

import warnings

warnings.warn(
    "backend.core.plan is deprecated; import from packages.plan",
    DeprecationWarning,
    stacklevel=2,
)
from packages.plan import *  # noqa: F401,F403