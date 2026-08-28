"""E3.3b — tenant subscription settings (tenant_config JSON)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from backend.core.audit import write_audit_sync
from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from backend.core.workflow.subscription import (
    effective_seat_cap,
    get_subscription,
    set_subscription,
)
from backend.database.pgvector_session import TenantConfig, get_pg_session

router = APIRouter(prefix="/api/tenant", tags=["tenant-subscription"])


def _add_calendar_years(base: datetime, years: int) -> datetime:
    """整数年：同月日推进；2/29 → 2/28。"""
    try:
        return base.replace(year=base.year + years)
    except ValueError:
        return base.replace(year=base.year + years, day=28)


def resolve_tenant_admin_expires(
    *,
    trial_days: Literal[7, 14] | None,
    renew_years: int | None,
    now: datetime | None = None,
) -> datetime:
    """tenant_admin 到期：试用 7/14 天，或从现在起整数年。"""
    n = now or datetime.utcnow()
    if trial_days is not None and renew_years is not None:
        raise ValueError("trial_and_years_mutex")
    if trial_days is None and renew_years is None:
        raise ValueError("expires_mode_required")
    if trial_days is not None:
        return n + timedelta(days=int(trial_days))
    assert renew_years is not None
    return _add_calendar_years(n, int(renew_years))


class SubscriptionBody(BaseModel):
    plan: str | None = Field(default=None, max_length=64)
    expires_at: datetime | None = None
    """自由到期日：仅 super_admin。tenant_admin 用 trial_days / renew_years。"""
    trial_days: Literal[7, 14] | None = None
    renew_years: int | None = Field(default=None, ge=1, le=30)
    seat_limit: int | None = Field(default=None, ge=0)
    paid_extra_seats: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _mutex_trial_years(self) -> SubscriptionBody:
        if self.trial_days is not None and self.renew_years is not None:
            raise ValueError("trial_days_and_renew_years_mutex")
        return self


def _audit_seat(
    *,
    tenant: TenantContext,
    action: str,
    before: Any,
    after: Any,
) -> None:
    write_audit_sync(
        {
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id,
            "action": action,
            "trace_id": "",
            "input_text": str(before),
            "output_text": str(after),
            "model": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
            "latency_ms": 0.0,
            "error_code": None,
            "ip_address": "",
            "user_agent": "",
            "created_at": datetime.utcnow(),
        }
    )


@router.put("/subscription")
async def put_subscription(
    body: SubscriptionBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    if tenant.role not in ("tenant_admin", "super_admin"):
        raise HTTPException(
            status_code=403,
            detail={"code": "SUB_403", "message": "tenant_admin_required"},
        )
    # 1A：tenant_admin 只能 paid_extra_seats + 受限到期；plan/seat_limit 仅 super_admin
    if body.seat_limit is not None and tenant.role != "super_admin":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "SEAT_LIMIT_FORBIDDEN",
                "message": "seat_limit_super_admin_only",
                "hint": "use_paid_extra_seats",
            },
        )
    if body.plan is not None and tenant.role != "super_admin":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PLAN_FORBIDDEN",
                "message": "plan_super_admin_only",
                "hint": "use_paid_extra_seats",
            },
        )

    expires_at = body.expires_at
    if tenant.role != "super_admin":
        if body.expires_at is not None:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "EXPIRES_FORBIDDEN",
                    "message": "expires_at_super_admin_only",
                    "hint": "use_trial_days_7_or_14_or_renew_years",
                },
            )
        if body.trial_days is not None or body.renew_years is not None:
            try:
                expires_at = resolve_tenant_admin_expires(
                    trial_days=body.trial_days,
                    renew_years=body.renew_years,
                )
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "EXPIRES_INVALID",
                        "message": str(e),
                    },
                ) from e
    elif body.trial_days is not None or body.renew_years is not None:
        # super_admin 也可走结构化字段；与 expires_at 互斥优先结构化
        if body.expires_at is not None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "EXPIRES_CONFLICT",
                    "message": "expires_at_vs_trial_or_years",
                },
            )
        try:
            expires_at = resolve_tenant_admin_expires(
                trial_days=body.trial_days,
                renew_years=body.renew_years,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail={"code": "EXPIRES_INVALID", "message": str(e)},
            ) from e

    sf = get_pg_session()
    with sf.Session() as session:
        row = (
            session.query(TenantConfig)
            .filter(TenantConfig.tenant_id == tenant.tenant_id)
            .one_or_none()
        )
        if row is None:
            row = TenantConfig(tenant_id=tenant.tenant_id, config={})
            session.add(row)
        cfg = dict(row.config or {}) if isinstance(row.config, dict) else {}
        before = get_subscription(cfg)
        row.config = set_subscription(
            cfg,
            plan=body.plan if tenant.role == "super_admin" else None,
            expires_at=expires_at,
            seat_limit=body.seat_limit if tenant.role == "super_admin" else None,
            paid_extra_seats=body.paid_extra_seats,
        )
        session.commit()
        after = get_subscription(row.config)
        if body.paid_extra_seats is not None and before.get("paid_extra_seats") != after.get(
            "paid_extra_seats"
        ):
            _audit_seat(
                tenant=tenant,
                action="tenant.seat.extra",
                before=before.get("paid_extra_seats"),
                after=after.get("paid_extra_seats"),
            )
        if (
            tenant.role == "super_admin"
            and body.seat_limit is not None
            and before.get("seat_limit") != after.get("seat_limit")
        ):
            _audit_seat(
                tenant=tenant,
                action="tenant.seat.limit",
                before=before.get("seat_limit"),
                after=after.get("seat_limit"),
            )
        if expires_at is not None and before.get("expires_at") != after.get("expires_at"):
            _audit_seat(
                tenant=tenant,
                action="tenant.subscription.expires",
                before=before.get("expires_at"),
                after=after.get("expires_at"),
            )
        return {
            "ok": True,
            "subscription": after,
            "effective_seat_cap": effective_seat_cap(after),
        }


@router.get("/subscription")
async def get_subscription_endpoint(
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        row = (
            session.query(TenantConfig)
            .filter(TenantConfig.tenant_id == tenant.tenant_id)
            .one_or_none()
        )
        cfg = dict(row.config or {}) if row and isinstance(row.config, dict) else {}
        sub = get_subscription(cfg)
        return {
            "subscription": sub,
            "effective_seat_cap": effective_seat_cap(sub),
        }
