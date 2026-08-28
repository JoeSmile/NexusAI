"""Deprecated shim — use `packages.skill_assets` (Task 75.8)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.skill_assets is deprecated; import from packages.skill_assets",
    DeprecationWarning,
    stacklevel=2,
)
from packages.skill_assets import *  # noqa: F401,F403