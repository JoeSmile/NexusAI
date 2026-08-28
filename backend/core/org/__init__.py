"""Deprecated shim — use `packages.org` (Task 75.8)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.org is deprecated; import from packages.org",
    DeprecationWarning,
    stacklevel=2,
)
from packages.org import *  # noqa: F401,F403