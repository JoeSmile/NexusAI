"""Deprecated shim — use `packages.skills` (Task 75.6)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.skills is deprecated; import from packages.skills",
    DeprecationWarning,
    stacklevel=2,
)
from packages.skills import *  # noqa: F401,F403