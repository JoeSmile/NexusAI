"""Deprecated shim — use `apps.api.routers` (Task 75.5)."""
from __future__ import annotations

import warnings

warnings.warn(
    "backend.routers is deprecated; import from apps.api.routers",
    DeprecationWarning,
    stacklevel=2,
)
from apps.api.routers import *  # noqa: F401,F403