"""Deprecated shim — use `packages.ab` (Task 75.8)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.ab is deprecated; import from packages.ab",
    DeprecationWarning,
    stacklevel=2,
)
from packages.ab import *  # noqa: F401,F403