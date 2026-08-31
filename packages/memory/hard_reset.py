"""Task 78.3 — drop L1 narrative on hard cap; never touch 77 belief.

`/reset` (78.4) must call ``drop_l1_narrative`` — do not fork a second reset.
"""

from __future__ import annotations

import os

from packages.database.vector_ops import delete_user_memory
from packages.memory.context_summarize import l1_warm_key
from packages.plan.retrieval_mode import estimate_prompt_tokens

_DEFAULT_HARD_TOKENS = 8000


def _hard_token_cap() -> int:
    raw = (os.getenv("MEMORY_HARD_RESET_TOKENS") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_HARD_TOKENS


def drop_l1_narrative(tenant_id: str, user_id: str, session_id: str) -> bool:
    """Delete rolling summary only. Belief Redis keys are never touched."""
    deleted = bool(
        delete_user_memory(tenant_id, user_id, l1_warm_key(session_id))
    )
    try:
        from packages.memory.memory_service import get_unified_memory_service

        get_unified_memory_service(tenant_id=tenant_id)._invalidate_mem_bundle(
            user_id
        )
    except Exception:
        pass
    return deleted


def maybe_hard_reset_l1(
    *,
    tenant_id: str,
    user_id: str,
    session_id: str,
    unarchived_texts: list[str],
    l1_raw: str = "",
) -> bool:
    l1 = (l1_raw or "").strip()
    if not l1:
        return False
    joined = "\n".join(str(t) for t in unarchived_texts if t)
    blob = f"{joined}\n{l1}".strip()
    if estimate_prompt_tokens(blob) <= _hard_token_cap():
        return False
    drop_l1_narrative(tenant_id, user_id, session_id)
    return True


def archive_all_live_turns(tenant_id: str, user_id: str, session_id: str) -> int:
    """Stamp archived_at on every live turn in this session (``/reset`` / ``/new``)."""
    from datetime import datetime

    from packages.database.pgvector_session import ChatMessage, get_pg_session

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        n = (
            session.query(ChatMessage)
            .filter_by(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
            .filter(ChatMessage.archived_at.is_(None))
            .update(
                {ChatMessage.archived_at: datetime.utcnow()},
                synchronize_session=False,
            )
        )
        session.commit()
    try:
        from packages.memory.memory_service import get_unified_memory_service

        get_unified_memory_service(tenant_id=tenant_id)._invalidate_mem_bundle(
            user_id
        )
    except Exception:
        pass
    return int(n or 0)


def session_hard_reset(tenant_id: str, user_id: str, session_id: str) -> dict[str, object]:
    """Shared ``/reset`` path: drop L0 live turns + L1. Never touches belief."""
    archived = archive_all_live_turns(tenant_id, user_id, session_id)
    dropped = drop_l1_narrative(tenant_id, user_id, session_id)
    return {"archived": archived, "l1_dropped": dropped}
