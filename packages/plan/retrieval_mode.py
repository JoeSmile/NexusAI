"""Dual-mode memory retrieval switch (Task 61 slice 4)."""

from __future__ import annotations

import os
from typing import Literal

RetrievalMode = Literal["A", "B"]

_MODE_A_MAX_CANDIDATES = 3
_MODE_B_MIN_CANDIDATES = 5
_LONG_DOC_CHARS = 500


def normalize_retrieval_mode(mode: str | None) -> RetrievalMode:
    m = (mode or "A").strip().upper()
    return "B" if m == "B" else "A"


def dual_mode_enabled() -> bool:
    return (os.getenv("MEMORY_DUAL_MODE_ENABLED", "1")).strip().lower() not in (
        "0",
        "false",
        "no",
    )


def choose_retrieval_mode(
    *,
    candidate_count: int,
    cold_items: list[dict] | None = None,
    query: str = "",
) -> RetrievalMode:
    """Mode A: direct load; Mode B: summary+id only at top level."""
    if not dual_mode_enabled():
        return "A"
    _ = query  # reserved for future query-length heuristic
    if candidate_count <= _MODE_A_MAX_CANDIDATES:
        return "A"
    if candidate_count > _MODE_B_MIN_CANDIDATES:
        return "B"
    for item in cold_items or []:
        if len(str(item.get("summary") or "")) >= _LONG_DOC_CHARS:
            return "B"
    return "A"


def estimate_prompt_tokens(text: str) -> int:
    from packages.prompt_tokens import estimate_tokens

    return estimate_tokens(text)


def token_budget_warning(assembled: str, *, budget: int) -> str | None:
    est = estimate_prompt_tokens(assembled)
    if est > budget:
        return f"context_budget_exceeded:{est}>{budget}"
    return None
