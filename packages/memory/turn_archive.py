"""Select which unarchived chat turns to stamp archived_at (Task 78.1)."""

from __future__ import annotations

import os
from collections.abc import Sequence

from packages.pipeline.context_messages import CONTEXT_TOKEN_BUDGET, HOT_HISTORY_TURNS
from packages.plan.retrieval_mode import estimate_prompt_tokens


def archive_window_limits() -> tuple[int, int]:
    """(max_turns, token_budget) — defaults match expand_hot_messages (10 / 8000)."""

    def _env_int(name: str, default: int) -> int:
        raw = (os.getenv(name) or "").strip()
        if not raw:
            return default
        try:
            return max(1, int(raw))
        except ValueError:
            return default

    return (
        _env_int("MEMORY_ARCHIVE_MAX_TURNS", HOT_HISTORY_TURNS),
        _env_int("MEMORY_ARCHIVE_TOKEN_BUDGET", CONTEXT_TOKEN_BUDGET),
    )


def select_turn_ids_to_archive(
    rows: Sequence[tuple[int, str]],
    *,
    max_turns: int,
    budget_tokens: int,
) -> list[int]:
    """Oldest ids that fall outside the live window. `rows` is chronological."""
    if not rows or max_turns < 1 or budget_tokens < 1:
        return []
    indexed = list(rows)
    keep = list(indexed[-max_turns:])
    while keep:
        joined = "\n".join(content for _id, content in keep)
        if estimate_prompt_tokens(joined) <= budget_tokens:
            break
        keep.pop(0)
    keep_ids = {i for i, _ in keep}
    return [i for i, _ in indexed if i not in keep_ids]
