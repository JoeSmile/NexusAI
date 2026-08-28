"""Deprecated shim — use ``packages.llm`` (Task 75.9)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.modules.llm is deprecated; import from packages.llm",
    DeprecationWarning,
    stacklevel=2,
)
from packages.llm import *  # noqa: F401,F403
