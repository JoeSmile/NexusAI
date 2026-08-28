"""Deprecated shim — use ``packages.channel`` (Task 75.9)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.modules.channel is deprecated; import from packages.channel",
    DeprecationWarning,
    stacklevel=2,
)
from packages.channel import *  # noqa: F401,F403
