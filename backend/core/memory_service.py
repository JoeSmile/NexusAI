"""Deprecated shim — use `packages.memory.memory_service` (Task 75.6)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.memory_service is deprecated; import from packages.memory.memory_service",
    DeprecationWarning,
    stacklevel=2,
)
from packages.memory.memory_service import *  # noqa: F401,F403