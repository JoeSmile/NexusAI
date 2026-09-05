"""Task 84 — primary/backup search + Redis spend caps (alert, do not refuse)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from packages.redis_tools import cache_key, get_sync_redis
from packages.search_service.adapter import (
    SearchAdapter,
    SearchAdapterError,
    SearchRequest,
    SearchResult,
    search_cap_config,
)

logger = logging.getLogger(__name__)


@dataclass
class SearchOutcome:
    hits: list[SearchResult] = field(default_factory=list)
    provider: str | None = None
    degrade_code: str | None = None
    cap_warned: bool = False


def _month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _day() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _keys(tenant_id: str) -> tuple[str, str, str]:
    tid = (tenant_id or "default").strip() or "default"
    return (
        cache_key("search", "cap", "global", _month()),
        cache_key("search", "cap", tid, f"day:{_day()}"),
        cache_key("search", "cap", tid, f"month:{_month()}"),
    )


def _over_cap(r: object, tenant_id: str) -> bool:
    caps = search_cap_config()
    g_key, d_key, m_key = _keys(tenant_id)
    try:
        g = int(r.get(g_key) or 0)  # type: ignore[union-attr]
        d = int(r.get(d_key) or 0)  # type: ignore[union-attr]
        m = int(r.get(m_key) or 0)  # type: ignore[union-attr]
    except Exception:
        return False
    return (
        g >= caps["global_month"]
        or d >= caps["tenant_day"]
        or m >= caps["tenant_month"]
    )


def _bump(r: object, tenant_id: str) -> None:
    g_key, d_key, m_key = _keys(tenant_id)
    try:
        n = int(r.incr(g_key))  # type: ignore[union-attr]
        if n == 1:
            r.expire(g_key, 40 * 24 * 3600)  # type: ignore[union-attr]
        n = int(r.incr(d_key))  # type: ignore[union-attr]
        if n == 1:
            r.expire(d_key, 2 * 24 * 3600)  # type: ignore[union-attr]
        n = int(r.incr(m_key))  # type: ignore[union-attr]
        if n == 1:
            r.expire(m_key, 40 * 24 * 3600)  # type: ignore[union-attr]
    except Exception:
        logger.debug("search cap incr skipped", exc_info=True)


def _alert_cap_once(r: object, tenant_id: str) -> None:
    tid = (tenant_id or "default").strip() or "default"
    flag = cache_key("search", "cap", tid, f"alert:{_day()}")
    try:
        created = r.set(flag, "1", nx=True, ex=2 * 24 * 3600)  # type: ignore[union-attr]
    except Exception:
        created = True
    if not created:
        return
    try:
        from packages.audit import write_audit_sync

        write_audit_sync(
            {
                "tenant_id": tid,
                "user_id": "system",
                "action": "search.cap_exceeded",
                "error_code": "SEARCH_CAP_EXCEEDED",
                "trace_id": f"search-cap:{tid}:{_day()}",
            }
        )
    except Exception:
        logger.debug("search cap audit skipped", exc_info=True)


def _try(adapter: SearchAdapter, req: SearchRequest) -> list[SearchResult]:
    try:
        return list(adapter.search(req) or [])
    except SearchAdapterError:
        raise
    except Exception as e:
        raise SearchAdapterError("adapter_failed") from e


def search_with_failover(
    primary: SearchAdapter,
    backup: SearchAdapter,
    req: SearchRequest,
) -> SearchOutcome:
    r = get_sync_redis(decode_responses=True)
    tid = req.tenant_id or ""
    warned = bool(r is not None and _over_cap(r, tid))
    if warned:
        _alert_cap_once(r, tid)

    try:
        hits = _try(primary, req)
        if hits:
            if r is not None:
                _bump(r, tid)
            return SearchOutcome(
                hits=hits,
                provider=primary.name,
                degrade_code="SEARCH_CAP_EXCEEDED" if warned else None,
                cap_warned=warned,
            )
    except SearchAdapterError:
        logger.debug("search primary failed", exc_info=True)

    try:
        hits = _try(backup, req)
        if hits:
            if r is not None:
                _bump(r, tid)
            code = "SEARCH_FAILOVER"
            return SearchOutcome(
                hits=hits,
                provider=backup.name,
                degrade_code=code,
                cap_warned=warned,
            )
    except SearchAdapterError:
        logger.debug("search backup failed", exc_info=True)

    return SearchOutcome(
        hits=[],
        degrade_code="SEARCH_BOTH_FAILED",
        cap_warned=warned,
    )
