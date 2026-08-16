"""G1/G8 seat_limit + G3 ordering + G7 F4 redact."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.core.memory_service import (
    UnifiedMemoryService,
    redact_student_names_in_text,
)
from backend.core.workflow.subscription import (
    PLAN_SEAT_LIMITS,
    SeatLimitExceeded,
    assert_seat_available,
    effective_seat_cap,
    get_subscription,
    set_subscription,
)


def test_plan_seat_limits_3_5_5():
    assert PLAN_SEAT_LIMITS["7800"] == 3
    assert PLAN_SEAT_LIMITS["9800"] == 5
    assert PLAN_SEAT_LIMITS["16800"] == 5


def test_set_subscription_paid_extra_and_cap():
    cfg = set_subscription({}, plan="edu-9800", paid_extra_seats=2)
    sub = get_subscription(cfg)
    assert sub["seat_limit"] == 5
    assert sub["paid_extra_seats"] == 2
    assert effective_seat_cap(sub) == 7


def test_assert_seat_available_raises():
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 3  # 单 UNION 查询
    cfg = set_subscription({}, plan="7800", paid_extra_seats=0)
    with pytest.raises(SeatLimitExceeded):
        assert_seat_available(session, tenant_id="t1", config=cfg, adding=1)


def test_assert_seat_available_ok_with_extra():
    session = MagicMock()
    session.execute.return_value.scalar.return_value = 3
    cfg = set_subscription({}, plan="7800", paid_extra_seats=1)
    assert_seat_available(session, tenant_id="t1", config=cfg, adding=1)


@pytest.mark.asyncio
async def test_tenant_admin_cannot_put_seat_limit():
    from fastapi import HTTPException

    from backend.core.auth.models import TenantContext
    from backend.routers.tenant_subscription import SubscriptionBody, put_subscription

    tenant = TenantContext(
        tenant_id="t1",
        user_id="u1",
        role="tenant_admin",
        extra_permissions=[],
        is_cross_tenant=False,
    )
    with pytest.raises(HTTPException) as ei:
        await put_subscription(
            SubscriptionBody(seat_limit=9999),
            tenant=tenant,
        )
    assert ei.value.status_code == 403
    assert ei.value.detail.get("code") == "SEAT_LIMIT_FORBIDDEN"


@pytest.mark.asyncio
async def test_tenant_admin_cannot_put_plan():
    from fastapi import HTTPException

    from backend.core.auth.models import TenantContext
    from backend.routers.tenant_subscription import SubscriptionBody, put_subscription

    tenant = TenantContext(
        tenant_id="t1",
        user_id="u1",
        role="tenant_admin",
        extra_permissions=[],
        is_cross_tenant=False,
    )
    with pytest.raises(HTTPException) as ei:
        await put_subscription(
            SubscriptionBody(plan="16800"),
            tenant=tenant,
        )
    assert ei.value.status_code == 403
    assert ei.value.detail.get("code") == "PLAN_FORBIDDEN"


@pytest.mark.asyncio
async def test_tenant_admin_cannot_put_freeform_expires():
    from fastapi import HTTPException

    from backend.core.auth.models import TenantContext
    from backend.routers.tenant_subscription import SubscriptionBody, put_subscription

    tenant = TenantContext(
        tenant_id="t1",
        user_id="u1",
        role="tenant_admin",
        extra_permissions=[],
        is_cross_tenant=False,
    )
    with pytest.raises(HTTPException) as ei:
        await put_subscription(
            SubscriptionBody(expires_at=datetime.utcnow() + timedelta(days=40)),
            tenant=tenant,
        )
    assert ei.value.status_code == 403
    assert ei.value.detail.get("code") == "EXPIRES_FORBIDDEN"


def test_resolve_tenant_admin_expires_trial_and_years():
    from backend.routers.tenant_subscription import resolve_tenant_admin_expires

    now = datetime(2026, 3, 1, 12, 0, 0)
    assert resolve_tenant_admin_expires(
        trial_days=7, renew_years=None, now=now
    ) == now + timedelta(days=7)
    assert resolve_tenant_admin_expires(
        trial_days=14, renew_years=None, now=now
    ) == now + timedelta(days=14)
    assert resolve_tenant_admin_expires(
        trial_days=None, renew_years=1, now=now
    ) == datetime(2027, 3, 1, 12, 0, 0)
    with pytest.raises(ValueError):
        resolve_tenant_admin_expires(trial_days=7, renew_years=1, now=now)


def test_redact_generation_output_g7():
    warm = {
        "entity:李明": json.dumps(
            {"name": "李明", "relation": "学生", "text": "李明"}
        )
    }
    out = redact_student_names_in_text(
        "今天给李明家长打电话",
        tenant_id="t1",
        warm=warm,
    )
    assert "李明" not in out
    assert "学生" in out


@pytest.mark.asyncio
async def test_warm_write_skips_stale_enqueued_at():
    svc = UnifiedMemoryService(tenant_id="t1")
    existing = MagicMock()
    existing.id = 9
    existing.updated_at = datetime.utcnow()
    existing.key = "entity:x"

    sess = MagicMock()
    sess.query.return_value.filter_by.return_value.first.return_value = existing
    sf = MagicMock()
    sf.Session.return_value.__enter__.return_value = sess
    sf.Session.return_value.__exit__.return_value = False

    with patch(
        "backend.database.pgvector_session.get_pg_session", return_value=sf
    ), patch(
        "backend.database.vector_ops.list_user_memories_by_prefix",
        return_value=[],
    ), patch(
        "backend.core.memory.supersede.supersede_user_domain", return_value=[]
    ), patch(
        "backend.database.embeddings.embed_text", return_value=None
    ):
        stale_ts = (datetime.utcnow() - timedelta(hours=1)).timestamp()
        out = await svc.write(
            "warm",
            user_id="u1",
            key="entity:x",
            value="{}",
            embed=False,
            enqueued_at=stale_ts,
        )
    assert out.get("skipped") == "stale_enqueued_at"
    assert out.get("id") == 9
