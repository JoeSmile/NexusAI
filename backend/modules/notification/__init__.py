"""Deprecated shim — use ``packages.notification`` (Task 75.9)."""
from __future__ import annotations
import warnings
warnings.warn(
    "backend.modules.notification is deprecated; import from packages.notification",
    DeprecationWarning,
    stacklevel=2,
)
from packages.notification import *  # noqa: F401,F403
