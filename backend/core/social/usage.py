"""Developer cost ledger helpers (Task 52)."""

from __future__ import annotations

import os
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.database.pgvector_session import SocialUsage

# Panel-ish unit costs (USD) — annotate when TikHub panel changes
COST_PROBE = Decimal("0.005")
COST_FETCH_PAGE = Decimal("0.01")
COST_DETAIL_BATCH = Decimal("0.005")
COST_ANALYSIS_ITEM = Decimal("0.002")  # LLM structure via harness
COST_REPLICA = Decimal("0.002")  # LLM replica via harness


def price_multiplier() -> Decimal:
    try:
        return Decimal(os.environ.get("SOCIAL_PRICE_MULTIPLIER", "3.0"))
    except Exception:
        return Decimal("3.0")


def record_usage(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
    platform: str | None,
    operation: str,
    item_count: int = 0,
    cost_usd: Decimal,
) -> SocialUsage:
    mult = price_multiplier()
    row = SocialUsage(
        tenant_id=tenant_id,
        user_id=user_id,
        platform=platform,
        operation=operation,
        item_count=item_count,
        cost_usd=cost_usd,
        price_usd=(cost_usd * mult).quantize(Decimal("0.0001")),
    )
    session.add(row)
    session.flush()
    return row


def global_cost_usd(session: Session) -> Decimal:
    from sqlalchemy import func

    total = session.query(func.coalesce(func.sum(SocialUsage.cost_usd), 0)).scalar()
    return Decimal(str(total or 0))


def cost_alert_exceeded(session: Session) -> bool:
    try:
        limit = Decimal(os.environ.get("SOCIAL_COST_ALERT_USD", "3.0"))
    except Exception:
        limit = Decimal("3.0")
    return global_cost_usd(session) >= limit
