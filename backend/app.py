"""Deprecated shim — use `apps.api.app` (Task 75.5)."""
from __future__ import annotations

import warnings

warnings.warn(
    "backend.app is deprecated; import from apps.api.app",
    DeprecationWarning,
    stacklevel=2,
)
from apps.api.app import *  # noqa: F401,F403
from apps.api.app import app  # noqa: F401