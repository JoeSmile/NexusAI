"""Deprecated shim — use `packages.tool_search` (Task 75.8)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.tool_search is deprecated; import from packages.tool_search",
    DeprecationWarning,
    stacklevel=2,
)
from packages.tool_search import *  # noqa: F401,F403