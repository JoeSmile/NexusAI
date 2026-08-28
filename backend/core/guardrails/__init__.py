"""Deprecated shim — use `packages.guardrails` (Task 75.6)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.core.guardrails is deprecated; import from packages.guardrails",
    DeprecationWarning,
    stacklevel=2,
)
from packages.guardrails import *  # noqa: F401,F403