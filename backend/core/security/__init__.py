"""Deprecated shim — use `packages.security` (Task 75.8)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.security is deprecated; import from packages.security",
    DeprecationWarning,
    stacklevel=2,
)
from packages.security import *  # noqa: F401,F403