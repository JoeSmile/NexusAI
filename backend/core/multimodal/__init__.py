"""Deprecated shim — use `packages.multimodal` (Task 75.8)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.multimodal is deprecated; import from packages.multimodal",
    DeprecationWarning,
    stacklevel=2,
)
from packages.multimodal import *  # noqa: F401,F403