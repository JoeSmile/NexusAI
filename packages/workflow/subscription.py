"""E3.3b — 订阅到期提醒 + seat 硬限（tenant_config JSON，禁虚构 tenants 表）。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class SeatLimitExceeded(Exception):
    """I-2(评审 08-15)：席位超限专用异常（替代字符串前缀匹配 ValueError）。"""

    def __init__(self, *, used: int, adding: int, cap: int):
        self.used = used
        self.adding = adding
        self.cap = cap
        super().__init__(
            f"SEAT_LIMIT:used={used}+{adding}>cap={cap}"
        )

_SUB_KEYS = (
    "plan",
    "expires_at",
    "last_notified_at",
    "seat_limit",
    "paid_extra_seats",
)

# 7800=3 / 9800=5 / 16800=5（拍板 3/5/5）
PLAN_SEAT_LIMITS: dict[str, int] = {
    "7800": 3,
    "edu-7800": 3,
    "9800": 5,
    "edu-9800": 5,
    "16800": 5,
    "edu-16800": 5,
}


def get_subscription(config: dict[str, Any] | None) -> dict[str, Any]:
    raw = (config or {}).get("subscription") if isinstance(config, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k in _SUB_KEYS:
        if k in raw:
            out[k] = raw.get(k)
    return out


def resolve_seat_limit(sub: dict[str, Any] | None) -> int | None:
    """返回有效座位数上限；None = 未配置席位策略（不拦截，兼容旧租户）。

    I-4(评审 08-15)：精确匹配档位，禁子串包含（plan "99800" 不得命中 "9800"）。
    """
    sub = sub or {}
    raw = sub.get("seat_limit")
    if raw is not None and str(raw).strip() != "":
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            pass
    plan = str(sub.get("plan") or "").strip()
    if plan in PLAN_SEAT_LIMITS:
        return PLAN_SEAT_LIMITS[plan]
    return None


def resolve_paid_extra(sub: dict[str, Any] | None) -> int:
    sub = sub or {}
    try:
        return max(0, int(sub.get("paid_extra_seats") or 0))
    except (TypeError, ValueError):
        return 0


def effective_seat_cap(sub: dict[str, Any] | None) -> int | None:
    base = resolve_seat_limit(sub)
    if base is None:
        return None
    return base + resolve_paid_extra(sub)


def count_tenant_seats(session: Any, tenant_id: str) -> int:
    """账号占用：active users ∪ active api_keys.user_id。"""
    from sqlalchemy import text

    # I-3(评审 08-15)：精确 union(users ∪ api_keys.user_id)，max() 会低估
    n = session.execute(
        text(
            """
            SELECT COUNT(DISTINCT u.user_id) FROM (
                SELECT user_id FROM users
                WHERE tenant_id = :tid AND COALESCE(is_active, true) = true
                UNION
                SELECT user_id FROM api_keys
                WHERE tenant_id = :tid AND COALESCE(is_active, true) = true
            ) u
            """
        ),
        {"tid": tenant_id},
    ).scalar()
    return int(n or 0)


def assert_seat_available(
    session: Any,
    *,
    tenant_id: str,
    config: dict[str, Any] | None = None,
    adding: int = 1,
) -> None:
    """超限 → 抛 SeatLimitExceeded 供路由转 403（I-2：专用异常，禁字符串匹配）。"""
    if config is None:
        from packages.database.pgvector_session import TenantConfig

        row = (
            session.query(TenantConfig)
            .filter(TenantConfig.tenant_id == tenant_id)
            .one_or_none()
        )
        config = dict(row.config or {}) if row and isinstance(row.config, dict) else {}
    sub = get_subscription(config)
    cap = effective_seat_cap(sub)
    if cap is None:
        return
    used = count_tenant_seats(session, tenant_id)
    if used + adding > cap:
        raise SeatLimitExceeded(used=used, adding=adding, cap=cap)


def set_subscription(
    config: dict[str, Any] | None,
    *,
    plan: str | None = None,
    expires_at: str | datetime | None = None,
    last_notified_at: str | datetime | None = None,
    seat_limit: int | None = None,
    paid_extra_seats: int | None = None,
) -> dict[str, Any]:
    cfg = dict(config or {})
    sub = dict(cfg.get("subscription") or {}) if isinstance(cfg.get("subscription"), dict) else {}
    if plan is not None:
        sub["plan"] = plan
        # 同步档位默认 seat_limit（可被显式 seat_limit 覆盖）
        if seat_limit is None and plan in PLAN_SEAT_LIMITS:
            sub["seat_limit"] = PLAN_SEAT_LIMITS[plan]
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
    if seat_limit is not None:
        sub["seat_limit"] = max(0, int(seat_limit))
    if paid_extra_seats is not None:
        sub["paid_extra_seats"] = max(0, int(paid_extra_seats))
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
    from packages.database.pgvector_session import TenantConfig, get_pg_session
    from packages.notification.service import list_tenant_admin_user_ids, notify

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
