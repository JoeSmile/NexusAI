"""S4 A5 — per-item memory role-drift filter + audit cooldown."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from packages.guardrails.output_guard import match_role_drift
from packages.memory.memory_service import MemoryBundle

logger = logging.getLogger(__name__)

MEMORY_BG_OMITTED_NOTICE = "该部分背景未载入。"
_LOCAL_COOLDOWN: dict[str, float] = {}
_LOCK = threading.Lock()


@dataclass
class DriftFilterReport:
    dropped_warm_keys: list[str] = field(default_factory=list)
    warned_cold_ids: list[str] = field(default_factory=list)


def _cooldown_sec() -> int:
    try:
        return max(60, int(os.getenv("MEMORY_DRIFT_AUDIT_COOLDOWN_SEC", "3600") or 3600))
    except ValueError:
        return 3600


def should_audit_drift_key(tenant_id: str, user_id: str, key: str) -> bool:
    """First hit for (tenant, user, key) audits; later hits in TTL are silent."""
    slot = f"mem:drift:{tenant_id}:{user_id}:{key}"
    ttl = _cooldown_sec()
    try:
        from packages.redis_tools import get_sync_redis

        r = get_sync_redis(decode_responses=True)
        if r is not None:
            ok = r.set(slot, "1", nx=True, ex=ttl)
            return bool(ok)
    except Exception:
        logger.debug("drift audit cooldown redis skipped", exc_info=True)
    now = time.monotonic()
    with _LOCK:
        prev = _LOCAL_COOLDOWN.get(slot)
        if prev is not None and now - prev < ttl:
            return False
        _LOCAL_COOLDOWN[slot] = now
        return True


def filter_bundle_role_drift(
    bundle: MemoryBundle,
    *,
    profile: str = "secretary",
) -> tuple[MemoryBundle, DriftFilterReport]:
    """Drop drifted warm keys. Cold / no-key items warn only (do not drop)."""
    report = DriftFilterReport()
    warm_out: dict[str, str] = {}
    for key, raw in (bundle.warm or {}).items():
        if match_role_drift(str(raw), profile=profile):
            report.dropped_warm_keys.append(str(key))
            continue
        warm_out[str(key)] = raw

    cold_out: list[dict[str, Any]] = []
    for item in bundle.cold or []:
        row = dict(item)
        blob = str(row.get("summary") or "")
        if match_role_drift(blob, profile=profile):
            cid = str(row.get("id") or row.get("session_id") or "")
            report.warned_cold_ids.append(cid)
            logger.warning("cold memory role-drift warn-only id=%s", cid or "-")
        cold_out.append(row)

    return (
        MemoryBundle(
            hot=list(bundle.hot or []),
            warm=warm_out,
            cold=cold_out,
            warm_meta=dict(bundle.warm_meta or {}),
        ),
        report,
    )
