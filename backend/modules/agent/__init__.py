"""Deprecated shim — use ``packages.agent`` (Task 75.9)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.modules.agent is deprecated; import from packages.agent",
    DeprecationWarning,
    stacklevel=2,
)
from packages.agent import *  # noqa: F401,F403
