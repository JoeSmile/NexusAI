"""Deprecated shim — use ``packages.auth`` (Task 75.1).

Kept for one Wave so leftover imports do not crash.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "backend.core.auth is deprecated; import from packages.auth",
    DeprecationWarning,
    stacklevel=2,
)

from packages.auth import *  # noqa: F401,F403
from packages.auth import __all__  # noqa: F401
