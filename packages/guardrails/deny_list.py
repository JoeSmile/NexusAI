"""Global deny-list for cheap gate (Task 39). Env substrings only; no regex / tenant map."""

from __future__ import annotations

import os


def load_deny_list() -> list[str]:
    """Parse PIPELINE_DENY_LIST (comma-separated); default empty.

    Terms are lowercased so they match NFKC+lower normalized input.
    """
    raw = os.getenv("PIPELINE_DENY_LIST", "") or ""
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def deny_list_hit(normalized_text: str, terms: list[str] | None = None) -> str | None:
    """Return first matching substring in normalized text, else None."""
    if not normalized_text:
        return None
    for term in terms if terms is not None else load_deny_list():
        if term and term in normalized_text:
            return term
    return None
