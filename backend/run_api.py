"""Deprecated shim — use `python -m apps.api.run_api` (Task 75.5)."""
from __future__ import annotations

import warnings

warnings.warn(
    "backend.run_api is deprecated; use apps.api.run_api",
    DeprecationWarning,
    stacklevel=2,
)
from apps.api.run_api import main

if __name__ == "__main__":
    main()