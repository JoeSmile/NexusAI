"""Deprecated shim — use `packages.capability` (Task 75.3)."""
from __future__ import annotations

import warnings

warnings.warn(
    "backend.core.capability is deprecated; import from packages.capability",
    DeprecationWarning,
    stacklevel=2,
)
from packages.capability import *  # noqa: F401,F403