"""Hang-wait notify routing + timeout escalate (Wave E3).

无主动推送；待办 = inbox。祖先链找 dept_manager；找不到或超时 →
escalated_at + audit（status 仍 pending，保证 E4 approve CAS）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from backend.core.audit import write_audit_sync
from backend.core.org.service import get_unit, list_memberships_for_unit
from backend.database.pgvector_session import PermissionRequest, get_pg_session

logger = logging.getLogger(__name__)

DEFAULT_HANG_ESCALATE_AFTER_SEC = 24 * 3600
_SCAN_INTERVAL_SEC = 60.0
_scanner_task: asyncio.Task[None] | None = None


def hang_escalate_after_seconds() -> float:
    raw = (os.getenv("HANG_ESCALATE_AFTER") or "").strip()
    if not raw:
        return float(DEFAULT_HANG_ESCALATE_AFTER_SEC)
    try:
        # 支持纯秒数或带单位后缀 h/m/s
        if raw.endswith("h"):
            return float(raw[:-1]) * 3600
        if raw.endswith("m"):
            return float(raw[:-1]) * 60
        if raw.endswith("s"):
            return float(raw[:-1])
        return float(raw)
    except ValueError:
        return float(DEFAULT_HANG_ESCALATE_AFTER_SEC)


@dataclass(frozen=True)
class HangRoute:
    """路由结果：dept_manager 用户列表；空则应升级 tenant_admin。"""

    manager_user_ids: tuple[str, ...]
    matched_org_unit_id: str | None
    escalate_to_tenant_admin: bool
    reason: str


def ancestor_unit_ids(path: str) -> list[str]:
    """path `/a/b/c/` → 自近及远 [`c`,`b`,`a`]。"""
    parts = [p for p in (path or "").split("/") if p]
    return list(reversed(parts))


def resolve_hang_route(
    session: Session,
    *,
    tenant_id: str,
    org_unit_id: str,
) -> HangRoute:
    """
    沿申请人部门祖先链找最近 dept_manager（membership 在该祖先单位上）。
    精确只匹配本部门会漏祖先经理 → 误升 tenant_admin。
    """
    unit = get_unit(session, tenant_id=tenant_id, unit_id=org_unit_id)
    if unit is None:
        return HangRoute(
            manager_user_ids=(),
            matched_org_unit_id=None,
            escalate_to_tenant_admin=True,
            reason="org_unit_missing",
        )

    for aid in ancestor_unit_ids(unit.path):
        mems = list_memberships_for_unit(session, tenant_id=tenant_id, org_unit_id=aid)
        managers = [
            m.user_id
            for m in mems
            if "dept_manager" in (m.business_roles or [])
        ]
        if managers:
            # 去重保序
            seen: set[str] = set()
            ordered: list[str] = []
            for uid in managers:
                if uid not in seen:
                    seen.add(uid)
                    ordered.append(uid)
            return HangRoute(
                manager_user_ids=tuple(ordered),
                matched_org_unit_id=aid,
                escalate_to_tenant_admin=False,
                reason="dept_manager",
            )

    return HangRoute(
        manager_user_ids=(),
        matched_org_unit_id=None,
        escalate_to_tenant_admin=True,
        reason="no_dept_manager",
    )


def _audit_escalate(
    *,
    tenant_id: str,
    user_id: str,
    run_id: str,
    node_id: str,
    reason: str,
) -> None:
    write_audit_sync(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": f"workflow.hang.{reason}",
            "trace_id": run_id,
            "input_text": "",
            "output_text": reason[:200],
            "model": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
            "latency_ms": 0.0,
            "error_code": None,
            "ip_address": "",
            "user_agent": "",
            "credential_kind": None,
            "key_id": None,
            "run_id": run_id,
            "node_id": node_id,
            "created_at": datetime.utcnow(),
        }
    )


def mark_escalated(
    session: Session,
    req: PermissionRequest,
    *,
    reason: str,
) -> bool:
    """
    打标 escalated_at（幂等）；status 保持 pending。
    reason: escalate_no_dept_manager | escalate_timeout
    """
    if req.escalated_at is not None:
        return False
    now = datetime.utcnow()
    req.escalated_at = now
    req.updated_at = now
    _audit_escalate(
        tenant_id=req.tenant_id,
        user_id=req.applicant_user_id,
        run_id=req.run_id,
        node_id=req.node_id,
        reason=reason,
    )
    return True


def notify_hang_pending(run_id: str, node_id: str) -> HangRoute | None:
    """挂起后调用：路由；无经理则立即 escalate_no_dept_manager。失败静默。"""
    try:
        sf = get_pg_session()
        with sf.Session() as session:
            req = (
                session.query(PermissionRequest)
                .filter(
                    PermissionRequest.run_id == run_id,
                    PermissionRequest.node_id == node_id,
                    PermissionRequest.status == "pending",
                )
                .one_or_none()
            )
            if req is None:
                return None
            route = resolve_hang_route(
                session,
                tenant_id=req.tenant_id,
                org_unit_id=req.org_unit_id,
            )
            if route.escalate_to_tenant_admin:
                mark_escalated(session, req, reason="escalate_no_dept_manager")
                session.commit()
            return route
    except Exception:
        logger.debug("notify_hang_pending failed", exc_info=True)
        return None


def maybe_escalate_timeout(
    session: Session,
    req: PermissionRequest,
    *,
    now: datetime | None = None,
) -> bool:
    """懒升级兜底：pending 且超时 → escalate_timeout。"""
    if req.status != "pending" or req.escalated_at is not None:
        return False
    now = now or datetime.utcnow()
    created = req.created_at or now
    age = (now - created).total_seconds()
    if age < hang_escalate_after_seconds():
        return False
    ok = mark_escalated(session, req, reason="escalate_timeout")
    return ok


def scan_hang_timeouts(*, limit: int = 100) -> int:
    """扫描 pending 超时请求并打标。返回新升级条数。"""
    sf = get_pg_session()
    n = 0
    cutoff = datetime.utcnow() - timedelta(seconds=hang_escalate_after_seconds())
    try:
        with sf.Session() as session:
            rows = (
                session.query(PermissionRequest)
                .filter(
                    PermissionRequest.status == "pending",
                    PermissionRequest.escalated_at.is_(None),
                    PermissionRequest.created_at <= cutoff,
                )
                .order_by(PermissionRequest.created_at.asc())
                .limit(limit)
                .all()
            )
            for req in rows:
                if mark_escalated(session, req, reason="escalate_timeout"):
                    n += 1
            if n:
                session.commit()
    except Exception:
        logger.debug("scan_hang_timeouts failed", exc_info=True)
    return n


def hang_visibility(session: Session, *, run_id: str) -> dict[str, Any]:
    """run 详情挂起可见性：待谁批 / 是否已升级。"""
    reqs = (
        session.query(PermissionRequest)
        .filter(
            PermissionRequest.run_id == run_id,
            PermissionRequest.status == "pending",
        )
        .all()
    )
    waiting_nodes: list[dict[str, Any]] = []
    for req in reqs:
        maybe_escalate_timeout(session, req)
        route = resolve_hang_route(
            session,
            tenant_id=req.tenant_id,
            org_unit_id=req.org_unit_id,
        )
        if req.escalated_at is not None or route.escalate_to_tenant_admin:
            waiting_for = "tenant_admin"
        else:
            waiting_for = "dept_manager"
        waiting_nodes.append(
            {
                "node_id": req.node_id,
                "needed_perm": req.needed_perm,
                "capability_id": req.capability_id,
                "requestable_mode": req.requestable_mode,
                "waiting_for": waiting_for,
                "escalated_at": (
                    req.escalated_at.isoformat() if req.escalated_at else None
                ),
                "matched_org_unit_id": route.matched_org_unit_id,
                "manager_user_ids": list(route.manager_user_ids),
                "approval_note": req.approval_note,
            }
        )
    if waiting_nodes and any(n.get("escalated_at") for n in waiting_nodes):
        session.commit()
    summary = None
    if waiting_nodes:
        if any(n["waiting_for"] == "tenant_admin" for n in waiting_nodes):
            summary = "待 tenant_admin 审批（已升级或无部门经理）"
        else:
            summary = "待 dept_manager 审批"
    return {"hang_summary": summary, "waiting_nodes": waiting_nodes}


async def _scan_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_SCAN_INTERVAL_SEC)
            scan_hang_timeouts()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("hang scan loop error", exc_info=True)


def start_hang_scanner() -> None:
    """进程内 interval 扫描（静默降级：失败不阻断启动）。"""
    global _scanner_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _scanner_task is not None and not _scanner_task.done():
        return
    _scanner_task = loop.create_task(_scan_loop(), name="hang-escalate-scanner")


def stop_hang_scanner() -> None:
    global _scanner_task
    if _scanner_task is not None and not _scanner_task.done():
        _scanner_task.cancel()
    _scanner_task = None
