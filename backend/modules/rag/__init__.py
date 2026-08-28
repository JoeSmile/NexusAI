"""Deprecated shim — use ``packages.rag`` (Task 75.9)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.modules.rag is deprecated; import from packages.rag",
    DeprecationWarning,
    stacklevel=2,
)
from packages.rag import *  # noqa: F401,F403
