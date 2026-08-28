"""Deprecated shim — use `packages.terms` (Task 75.8)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.terms is deprecated; import from packages.terms",
    DeprecationWarning,
    stacklevel=2,
)
from packages.terms import *  # noqa: F401,F403