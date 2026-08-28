"""Deprecated shim — use `packages.content_ops` (Task 75.8)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.content_ops is deprecated; import from packages.content_ops",
    DeprecationWarning,
    stacklevel=2,
)
from packages.content_ops import *  # noqa: F401,F403