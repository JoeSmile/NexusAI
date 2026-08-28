"""Deprecated shim — use `packages.harness` (Task 75.6)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.harness is deprecated; import from packages.harness",
    DeprecationWarning,
    stacklevel=2,
)
from packages.harness import *  # noqa: F401,F403