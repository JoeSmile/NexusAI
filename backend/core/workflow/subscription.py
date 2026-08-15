"""E3.3b — 订阅到期提醒（tenant_config JSON，禁虚构 tenants 表）。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_SUB_KEYS = ("plan", "expires_at", "last_notified_at")


def get_subscription(config: dict[str, Any] | None) -> dict[str, Any]:
    raw = (config or {}).get("subscription") if isinstance(config, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {k: raw.get(k) for k in _SUB_KEYS if k in raw}


def set_subscription(
    config: dict[str, Any] | None,
    *,
    plan: str | None = None,
    expires_at: str | datetime | None = None,
    last_notified_at: str | datetime | None = None,
) -> dict[str, Any]:
    cfg = dict(config or {})
    sub = dict(cfg.get("subscription") or {}) if isinstance(cfg.get("subscription"), dict) else {}
    if plan is not None:
        sub["plan"] = plan
    if expires_at is not None:
        sub["expires_at"] = (
            expires_at.isoformat() if isinstance(expires_at, datetime) else str(expires_at)
        )
    if last_notified_at is not None:
        sub["last_notified_at"] = (
            last_notified_at.isoformat()
            if isinstance(last_notified_at, datetime)
            else str(last_notified_at)
        )
    cfg["subscription"] = sub
    return cfg


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def scan_subscription_expiring(
    *,
    within_days: int = 30,
    now: datetime | None = None,
) -> dict[str, int]:
    from backend.database.pgvector_session import TenantConfig, get_pg_session
    from backend.modules.notification.service import list_tenant_admin_user_ids, notify

    now = now or datetime.utcnow()
    horizon = now + timedelta(days=within_days)
    notified = 0
    skipped = 0
    sf = get_pg_session()
    with sf.Session() as session:
        rows = session.query(TenantConfig).all()
        for row in rows:
            cfg = dict(row.config or {}) if isinstance(row.config, dict) else {}
            sub = get_subscription(cfg)
            exp = _parse_dt(sub.get("expires_at"))
            if exp is None:
                skipped += 1
                continue
            if exp > horizon:
                skipped += 1
                continue
            last = _parse_dt(sub.get("last_notified_at"))
            # 未过期：30d 窗口内只提醒一次；过期后每日一次
            if exp >= now:
                if last is not None:
                    skipped += 1
                    continue
            else:
                if last is not None and last.date() == now.date():
                    skipped += 1
                    continue
            admins = list_tenant_admin_user_ids(session, row.tenant_id)
            payload = {
                "plan": sub.get("plan"),
                "expires_at": exp.isoformat(),
            }
            for uid in admins:
                try:
                    notify(row.tenant_id, uid, "subscription.expiring", payload)
                    notified += 1
                except Exception:
                    logger.debug("subscription.expiring notify failed", exc_info=True)
            row.config = set_subscription(cfg, last_notified_at=now)
            session.add(row)
        session.commit()
    return {"notified": notified, "skipped": skipped}
