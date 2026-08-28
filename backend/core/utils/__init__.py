"""Deprecated shim — use `packages.utils` (Task 75.8)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.utils is deprecated; import from packages.utils",
    DeprecationWarning,
    stacklevel=2,
)
from packages.utils import *  # noqa: F401,F403