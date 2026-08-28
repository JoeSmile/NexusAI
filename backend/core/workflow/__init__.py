"""Deprecated shim — use `packages.workflow` (Task 75.4)."""
from __future__ import annotations

import warnings

warnings.warn(
    "backend.core.workflow is deprecated; import from packages.workflow",
    DeprecationWarning,
    stacklevel=2,
)
from packages.workflow import *  # noqa: F401,F403