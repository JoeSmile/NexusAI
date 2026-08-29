"""Exact cache helpers for chat→workflow bridge (R-I#6 / 拍板 6A)."""

from __future__ import annotations

import logging

from sqlalchemy import text

from packages.database.pgvector_session import get_pg_session

logger = logging.getLogger(__name__)


def exact_cache_key(tenant_id: str, user_id: str, query_hash: str) -> str:
    return f"exact:{tenant_id}:{user_id}:{query_hash}"


def invalidate_exact_cache(tenant_id: str, user_id: str, query_hash: str) -> bool:
    """DEL exact:{tid}:{uid}:{qhash}. Fail-soft; returns True if a row was deleted."""
    if not query_hash:
        return False
    key = exact_cache_key(tenant_id, user_id, query_hash)
    try:
        sf = get_pg_session()
        with sf.Session() as session:
            res = session.execute(
                text("DELETE FROM cache_entries WHERE cache_key = :k"),
                {"k": key},
            )
            session.commit()
            return bool(getattr(res, "rowcount", 0))
    except Exception:
        logger.debug("invalidate_exact_cache failed key=%s", key, exc_info=True)
        return False
