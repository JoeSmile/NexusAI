"""LLM key pool selection — round-robin over model-scoped chains (Task 72)."""

from __future__ import annotations

import logging

from packages.key_repository import LLMKey

logger = logging.getLogger(__name__)


def pick_key_from_chain(
    chain: list[LLMKey],
    *,
    tenant_id: str,
    model: str,
) -> LLMKey | None:
    """Pick one key from the chain.

    With Redis: round-robin via ``INCR llm:key:rr:{tenant}:{model}``.
    Without Redis: stable ``chain[0]`` (known degradation, not silent round-robin).
    """
    if not chain:
        return None
    tid = tenant_id or "default"
    m = (model or "").strip() or "default"
    try:
        from packages.redis_tools import get_sync_redis

        client = get_sync_redis(decode_responses=True)
        if client is not None:
            n = int(client.incr(f"llm:key:rr:{tid}:{m}"))
            return chain[(n - 1) % len(chain)]
    except Exception:
        logger.debug("key pool round-robin skipped (no redis)", exc_info=True)
    # No Redis: not round-robin — document in call sites (Task 72 D10)
    return chain[0]
