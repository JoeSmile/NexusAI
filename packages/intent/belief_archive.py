"""Archive ended-task belief into warm memory (Task 77.3). Never raise."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ARCHIVE_KEY = "funnel_task_archive"
_MAX_SUMMARY = 400


async def archive_ended_belief(
    *,
    tenant_id: str,
    user_id: str,
    session_id: str,
    belief: dict[str, Any],
) -> None:
    summary = str(belief.get("summary") or "").strip()[:_MAX_SUMMARY]
    if not summary:
        return
    try:
        from packages.memory.memory_service import get_unified_memory_service

        mem = get_unified_memory_service(tenant_id=tenant_id)
        await mem.write(
            "warm",
            user_id=user_id,
            session_id=session_id,
            key=ARCHIVE_KEY,
            value=summary,
            confidence=0.4,
            source="intent_funnel",
            embed=False,
        )
    except Exception:
        logger.debug("belief archive failed", exc_info=True)
