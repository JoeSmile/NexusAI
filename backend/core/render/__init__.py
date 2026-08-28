"""Deprecated shim — use `packages.render` (Task 75.8)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.render is deprecated; import from packages.render",
    DeprecationWarning,
    stacklevel=2,
)
from packages.render import *  # noqa: F401,F403