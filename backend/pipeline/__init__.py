"""Deprecated shim — use `packages.pipeline` (Task 75.2)."""
from __future__ import annotations

import warnings

warnings.warn(
    "backend.pipeline is deprecated; import from packages.pipeline",
    DeprecationWarning,
    stacklevel=2,
)
from packages.pipeline import *  # noqa: F401,F403