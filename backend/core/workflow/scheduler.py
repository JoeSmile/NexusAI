"""E3.4 — cron 定时执行器（分钟/小时/日三档 + SKIP LOCKED）。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_SCAN_INTERVAL_SEC = 60.0
_scanner_task: asyncio.Task[None] | None = None


def parse_cron_next(cron: str, *, after: datetime | None = None) -> datetime:
    """V1：仅支持 ``m h * * *``（分 时 日=日 月=月 周=*）。

    例：每天 8 点 = ``0 8 * * *``。
    """
    parts = (cron or "").strip().split()
    if len(parts) != 5:
        raise ValueError(f"unsupported_cron:{cron}")
    minute_s, hour_s, dom, month, dow = parts
    if dom != "*" or month != "*" or dow != "*":
        raise ValueError(f"unsupported_cron_fields:{cron}")
    try:
        minute = int(minute_s)
        hour = int(hour_s)
    except ValueError as exc:
        raise ValueError(f"unsupported_cron:{cron}") from exc
    if not (0 <= minute <= 59 and 0 <= hour <= 23):
        raise ValueError(f"unsupported_cron_range:{cron}")

    now = after or datetime.utcnow()
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return candidate


def validate_grants_before_execute(
    session: Any,
    *,
    tenant_id: str,
    workflow_id: str,
    acting_user_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """E3.5 — run 执行前校验：过期且 auto_renew → 续；否则标 expired。"""
    from backend.core.workflow.grants import (
        normalize_request_policy,
        renew_grant,
    )
    from backend.database.pgvector_session import Workflow, WorkflowGrant

    now = now or datetime.utcnow()
    wf = (
        session.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id)
        .one_or_none()
    )
    policy = normalize_request_policy(
        dict(wf.request_policy) if wf and wf.request_policy else None
    )
    renewed = 0
    expired = 0
    grants = (
        session.query(WorkflowGrant)
        .filter(
            WorkflowGrant.tenant_id == tenant_id,
            WorkflowGrant.workflow_id == workflow_id,
            WorkflowGrant.applicant_user_id == acting_user_id,
            WorkflowGrant.revoked_at.is_(None),
            WorkflowGrant.expires_at <= now,
        )
        .all()
    )
    for g in grants:
        if policy.get("auto_renew"):
            ng = renew_grant(session, grant=g, request_policy=policy, now=now)
            if ng is not None:
                renewed += 1
        else:
            from backend.database.pgvector_session import PermissionRequest

            req = (
                session.query(PermissionRequest)
                .filter(PermissionRequest.id == g.request_id)
                .one_or_none()
            )
            if req and req.status in ("approved", "auto_approved"):
                req.status = "expired"
                req.updated_at = now
                expired += 1
    return {"renewed": renewed, "expired": expired}


def _resolve_schedule_scope(session, sched):
    """F2(评审 08-15):created_by 无 primary org → 用创建时快照的 org_unit_id 构造
    scope(教育版主播可能未绑 org,resolve_org_scope 失败会静默 skip)。"""
    from backend.core.org.scope import OrgScope, resolve_org_scope

    try:
        return resolve_org_scope(
            session,
            tenant_id=sched.tenant_id,
            user_id=sched.created_by,
            platform_role="user",
            is_cross_tenant=False,
        )
    except Exception:
        logger.warning(
            "scheduler scope fallback org_unit_id=%s user=%s",
            sched.org_unit_id,
            sched.created_by,
        )
        return OrgScope(
            tenant_id=sched.tenant_id,
            user_id=sched.created_by,
            platform_role="user",
            primary_org_unit_id=sched.org_unit_id,
            org_unit_ids=frozenset({sched.org_unit_id})
            if sched.org_unit_id
            else frozenset(),
            subtree_paths=frozenset(),
            business_roles=frozenset(),
        )


def _user_still_valid(session: Session, *, tenant_id: str, user_id: str) -> bool:
    """I6：created_by 对应用户须仍有 active api_key。"""
    from backend.database.pgvector_session import ApiKey

    if not user_id:
        return False
    row = (
        session.query(ApiKey.id)
        .filter(
            ApiKey.tenant_id == tenant_id,
            ApiKey.user_id == user_id,
            ApiKey.is_active.is_(True),
        )
        .first()
    )
    return row is not None


def _audit_schedule(
    *,
    tenant_id: str,
    user_id: str,
    action: str,
    input_text: str = "",
    output_text: str = "",
    error_code: str | None = None,
) -> None:
    from backend.core.audit import write_audit_sync

    write_audit_sync(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": action,
            "trace_id": "",
            "input_text": (input_text or "")[:500],
            "output_text": (output_text or "")[:500],
            "model": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
            "latency_ms": 0.0,
            "error_code": error_code,
            "ip_address": "",
            "user_agent": "",
            "created_at": datetime.utcnow(),
        }
    )


def _advance_next(session: Session, sched: Any, *, now: datetime) -> None:
    try:
        sched.next_run_at = parse_cron_next(sched.cron, after=now)
        sched.updated_at = now
        session.commit()
    except ValueError:
        sched.enabled = False
        sched.updated_at = now
        session.commit()


def scan_due_schedules(*, now: datetime | None = None, limit: int = 50) -> dict[str, int]:
    from packages.auth.models import TenantContext
    from backend.core.workflow import runner as run_svc
    from backend.database.pgvector_session import (
        ScheduledRun,
        WorkflowRun,
        get_pg_session,
    )

    now = now or datetime.utcnow()
    triggered = 0
    skipped = 0
    sf = get_pg_session()
    with sf.Session() as session:
        locked = session.execute(
            text("SELECT pg_try_advisory_lock(:k)"),
            {"k": 41030417},
        ).scalar()
        if not locked:
            return {"triggered": 0, "skipped": 0, "lock": 0}
        try:
            rows = session.execute(
                text(
                    """
                    SELECT id FROM scheduled_runs
                    WHERE enabled = true AND next_run_at <= :now
                    ORDER BY next_run_at ASC
                    LIMIT :lim
                    FOR UPDATE SKIP LOCKED
                    """
                ),
                {"now": now, "lim": limit},
            ).fetchall()
            for (sid,) in rows:
                sched = (
                    session.query(ScheduledRun)
                    .filter(ScheduledRun.id == sid)
                    .one_or_none()
                )
                if sched is None or not sched.enabled:
                    skipped += 1
                    continue

                # I6：触发前校验 created_by 仍有效
                if not _user_still_valid(
                    session, tenant_id=sched.tenant_id, user_id=sched.created_by
                ):
                    _audit_schedule(
                        tenant_id=sched.tenant_id,
                        user_id=sched.created_by,
                        action="workflow.schedule.user_invalid",
                        input_text=sched.id,
                        output_text=sched.workflow_id,
                        error_code="SCHEDULE_USER_INACTIVE",
                    )
                    sched.enabled = False
                    sched.updated_at = now
                    session.commit()
                    skipped += 1
                    continue

                # 上一 run 未终态不重触
                inflight = (
                    session.query(WorkflowRun)
                    .filter(
                        WorkflowRun.tenant_id == sched.tenant_id,
                        WorkflowRun.workflow_id == sched.workflow_id,
                        WorkflowRun.status.in_(
                            ("pending", "running", "suspended", "waiting_child")
                        ),
                    )
                    .count()
                )
                if inflight > 0:
                    skipped += 1
                    _advance_next(session, sched, now=now)
                    continue

                tenant = TenantContext(
                    sched.tenant_id,
                    sched.created_by,
                    "user",
                    [],
                    False,
                )
                # I3：授权校验单独 try——异常 fail-closed，绝不当通过继续 start_run
                try:
                    validate_grants_before_execute(
                        session,
                        tenant_id=sched.tenant_id,
                        workflow_id=sched.workflow_id,
                        acting_user_id=sched.created_by,
                        now=now,
                    )
                    session.commit()
                except Exception as exc:
                    logger.warning(
                        "schedule auth_check failed sid=%s: %s",
                        sched.id,
                        exc,
                        exc_info=True,
                    )
                    session.rollback()
                    sched = (
                        session.query(ScheduledRun)
                        .filter(ScheduledRun.id == sid)
                        .one_or_none()
                    )
                    if sched is None:
                        skipped += 1
                        continue
                    _audit_schedule(
                        tenant_id=sched.tenant_id,
                        user_id=sched.created_by,
                        action="workflow.run.auth_check_failed",
                        input_text=sched.workflow_id,
                        output_text=f"{sched.id}:{exc!s}"[:500],
                        error_code="AUTH_GRANT_VALIDATE",
                    )
                    _advance_next(session, sched, now=now)
                    skipped += 1
                    continue

                try:
                    org_scope = _resolve_schedule_scope(session, sched)
                    out = run_svc.start_run(
                        session,
                        tenant=tenant,
                        org_scope=org_scope,
                        workflow_id=sched.workflow_id,
                        run_inputs=dict(sched.run_inputs or {}),
                    )
                    session.commit()
                    run_id = out.get("id") or out.get("run_id")
                    if run_id:
                        run_svc.schedule_execute(str(run_id))
                    triggered += 1
                except Exception:
                    logger.warning(
                        "scheduled run failed sid=%s", sched.id, exc_info=True
                    )
                    session.rollback()
                    skipped += 1
                    sched = (
                        session.query(ScheduledRun)
                        .filter(ScheduledRun.id == sid)
                        .one_or_none()
                    )
                    if sched is None:
                        continue
                _advance_next(session, sched, now=now)
        finally:
            session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": 41030417})
    return {"triggered": triggered, "skipped": skipped, "lock": 1}


def create_scheduled_run(
    session: Session,
    *,
    tenant_id: str,
    workflow_id: str,
    cron: str,
    created_by: str,
    run_inputs: dict[str, Any] | None = None,
    enabled: bool = True,
) -> Any:
    from backend.database.pgvector_session import ScheduledRun, Workflow

    now = datetime.utcnow()
    next_at = parse_cron_next(cron, after=now)
    # F2(评审 08-15):org_unit_id = 创建时 workflow 的 org 快照(触发不依赖 created_by 的 org)
    wf = (
        session.query(Workflow)
        .filter(Workflow.tenant_id == tenant_id, Workflow.id == workflow_id)
        .one_or_none()
    )
    org_unit_id = wf.org_unit_id if wf is not None else ""
    if not org_unit_id:
        raise ValueError("workflow_org_required: workflow not found or missing org_unit_id")
    row = ScheduledRun(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        cron=cron,
        next_run_at=next_at,
        enabled=enabled,
        run_inputs=run_inputs or {},
        org_unit_id=org_unit_id,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    return row


async def _scan_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_SCAN_INTERVAL_SEC)
            scan_due_schedules()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("schedule scan loop error", exc_info=True)


def start_schedule_scanner() -> None:
    global _scanner_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _scanner_task is not None and not _scanner_task.done():
        return
    _scanner_task = loop.create_task(_scan_loop(), name="workflow-schedule-scanner")


def stop_schedule_scanner() -> None:
    global _scanner_task
    if _scanner_task is not None and not _scanner_task.done():
        _scanner_task.cancel()
    _scanner_task = None
