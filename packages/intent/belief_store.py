"""Current-task belief in Redis (Task 77). Fail-open: Redis down → empty."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from packages.redis_tools import cache_key, get_sync_redis

logger = logging.getLogger(__name__)

BELIEF_TTL_SECONDS = 30 * 60
_PART = re.compile(r"[^A-Za-z0-9._-]+")


def _part(value: str) -> str:
    cleaned = _PART.sub("_", (value or "").strip())[:80]
    return cleaned or "_"


def belief_redis_key(tenant_id: str, user_id: str, session_id: str) -> str:
    """CACHE.md: ``belief:cur:{tid}:{uid}:{session}``."""
    rest = f"{_part(user_id)}:{_part(session_id)}"
    return cache_key("belief", "cur", _part(tenant_id), rest)


def _client() -> Any | None:
    try:
        return get_sync_redis(decode_responses=True)
    except Exception:
        logger.debug("belief redis client failed", exc_info=True)
        return None


def get_belief(tenant_id: str, user_id: str, session_id: str) -> dict[str, Any] | None:
    r = _client()
    if r is None:
        return None
    key = belief_redis_key(tenant_id, user_id, session_id)
    try:
        raw = r.get(key)
    except Exception:
        logger.debug("belief get failed", exc_info=True)
        return None
    if not raw:
        return None
    try:
        row = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return row if isinstance(row, dict) else None


def set_belief(
    tenant_id: str,
    user_id: str,
    session_id: str,
    payload: dict[str, Any],
) -> bool:
    r = _client()
    if r is None:
        return False
    key = belief_redis_key(tenant_id, user_id, session_id)
    try:
        body = json.dumps(payload, ensure_ascii=False)
        r.set(key, body, ex=BELIEF_TTL_SECONDS)
        return True
    except Exception:
        logger.debug("belief set failed", exc_info=True)
        return False


def delete_belief(tenant_id: str, user_id: str, session_id: str) -> bool:
    r = _client()
    if r is None:
        return False
    key = belief_redis_key(tenant_id, user_id, session_id)
    try:
        r.delete(key)
        return True
    except Exception:
        logger.debug("belief delete failed", exc_info=True)
        return False
