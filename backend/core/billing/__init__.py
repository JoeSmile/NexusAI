"""Deprecated shim — use `packages.billing` (Task 75.8)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.billing is deprecated; import from packages.billing",
    DeprecationWarning,
    stacklevel=2,
)
from packages.billing import *  # noqa: F401,F403