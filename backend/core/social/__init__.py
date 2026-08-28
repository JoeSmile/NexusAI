"""Deprecated shim — use `packages.social` (Task 75.8)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.social is deprecated; import from packages.social",
    DeprecationWarning,
    stacklevel=2,
)
from packages.social import *  # noqa: F401,F403