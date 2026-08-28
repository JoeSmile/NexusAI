"""Deprecated shim — use `packages.memory` (Task 75.6)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.memory is deprecated; import from packages.memory",
    DeprecationWarning,
    stacklevel=2,
)
from packages.memory import *  # noqa: F401,F403