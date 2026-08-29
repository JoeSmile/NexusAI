"""Workflow grant helpers (Wave E2).

caps 不并进 TenantContext.extra_permissions；命中 = (workflow_id, capability_id)
∈ 活跃 grant.caps。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from packages.org.scope import OrgScope, assert_org_access
from packages.database.pgvector_session import PermissionRequest, WorkflowGrant
from packages.auth.models import TenantContext
from packages.workflow.security_gates import RequestableMode

DEFAULT_TTL_DAYS = 90
DEFAULT_REQUEST_POLICY: dict[str, Any] = {
    "scope": "recurring",
    "default_ttl_days": DEFAULT_TTL_DAYS,
    "auto_renew": False,
}


@dataclass(frozen=True)
class ActiveGrantLookup:
    tenant_id: str
    workflow_id: str
    applicant_user_id: str
    capability_id: str


_grant_lookup: ContextVar[ActiveGrantLookup | None] = ContextVar(
    "workflow_grant_lookup", default=None
)


@contextmanager
def grant_auth_context(
    *,
    tenant_id: str,
    workflow_id: str,
    applicant_user_id: str,
    capability_id: str,
) -> Iterator[None]:
    """Runner 在 invoke 前设置；_check_permission 可读 DB 命中。"""
    tok = _grant_lookup.set(
        ActiveGrantLookup(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            applicant_user_id=applicant_user_id,
            capability_id=capability_id,
        )
    )
    try:
        yield
    finally:
        _grant_lookup.reset(tok)


def normalize_request_policy(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(DEFAULT_REQUEST_POLICY)
    if not raw:
        return base
    scope = str(raw.get("scope") or base["scope"]).strip().lower()
    if scope not in ("single", "recurring"):
        scope = "recurring"
    try:
        ttl = int(raw.get("default_ttl_days") or base["default_ttl_days"])
    except (TypeError, ValueError):
        ttl = DEFAULT_TTL_DAYS
    if ttl < 1:
        ttl = DEFAULT_TTL_DAYS
    # WaveE_3: auto_renew 实现；本 Wave 只存字段，强制 false 也可，尊重写入便于后续
    auto_renew = bool(raw.get("auto_renew", False))
    return {"scope": scope, "default_ttl_days": ttl, "auto_renew": auto_renew}


def cap_entry(*, capability_id: str, permission: str) -> dict[str, str]:
    return {"capability_id": capability_id, "permission": permission}


def caps_cover(caps: Any, *, capability_id: str) -> bool:
    if not isinstance(caps, list):
        return False
    for item in caps:
        if isinstance(item, dict) and str(item.get("capability_id") or "") == capability_id:
            return True
    return False


def find_active_grant_covering(
    session: Session,
    *,
    tenant_id: str,
    workflow_id: str,
    applicant_user_id: str,
    capability_id: str,
    now: datetime | None = None,
) -> WorkflowGrant | None:
    now = now or datetime.utcnow()
    rows = (
        session.query(WorkflowGrant)
        .filter(
            WorkflowGrant.tenant_id == tenant_id,
            WorkflowGrant.workflow_id == workflow_id,
            WorkflowGrant.applicant_user_id == applicant_user_id,
            WorkflowGrant.revoked_at.is_(None),
            WorkflowGrant.expires_at > now,
        )
        .all()
    )
    for g in rows:
        if caps_cover(g.caps, capability_id=capability_id):
            return g
    return None


def current_grant_covers_capability() -> bool:
    """供 invoke._check_permission：context + DB 活跃 grant。"""
    ctx = _grant_lookup.get()
    if ctx is None:
        return False
    from packages.database.pgvector_session import get_pg_session

    sf = get_pg_session()
    with sf.Session() as session:
        g = find_active_grant_covering(
            session,
            tenant_id=ctx.tenant_id,
            workflow_id=ctx.workflow_id,
            applicant_user_id=ctx.applicant_user_id,
            capability_id=ctx.capability_id,
        )
        return g is not None


def is_eligible_approver(
    tenant: TenantContext,
    org_scope: OrgScope,
    *,
    resource_org_unit_id: str,
    requestable_mode: RequestableMode,
    session: Session | None = None,
) -> bool:
    """
    与审批资格同条件（拍板）：
    - sensitive → 仅 tenant_admin / super_admin
    - true → dept_manager（org 覆盖）或 tenant_admin / super_admin
    """
    role = (tenant.role or "").strip()
    if role in ("tenant_admin", "super_admin"):
        return True
    if requestable_mode == "sensitive":
        return False
    if "dept_manager" not in (org_scope.business_roles or frozenset()):
        return False
    try:
        assert_org_access(org_scope, resource_org_unit_id, session=session)
    except Exception:
        return False
    return True


def issue_auto_grant(
    session: Session,
    *,
    tenant_id: str,
    workflow_id: str,
    run_id: str,
    node_id: str,
    applicant_user_id: str,
    needed_perm: str,
    org_unit_id: str,
    capability_id: str,
    requestable_mode: RequestableMode,
    approval_note: str | None,
    request_policy: dict[str, Any] | None,
) -> tuple[PermissionRequest, WorkflowGrant]:
    """同一事务内写 auto_approved request + grant(origin=auto_grant)。调用方 commit。"""
    policy = normalize_request_policy(request_policy)
    now = datetime.utcnow()
    req = PermissionRequest(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        run_id=run_id,
        node_id=node_id,
        applicant_user_id=applicant_user_id,
        needed_perm=needed_perm,
        org_unit_id=org_unit_id,
        capability_id=capability_id,
        status="auto_approved",
        reviewed_by=applicant_user_id,
        reviewed_at=now,
        review_reason="auto_grant",
        approval_note=approval_note,
        requestable_mode=requestable_mode,
        created_at=now,
        updated_at=now,
    )
    session.add(req)
    grant = WorkflowGrant(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        request_id=req.id,
        workflow_id=workflow_id,
        scope=str(policy["scope"]),
        applicant_user_id=applicant_user_id,
        caps=[cap_entry(capability_id=capability_id, permission=needed_perm)],
        issued_at=now,
        expires_at=now + timedelta(days=int(policy["default_ttl_days"])),
        revoked_at=None,
        origin="auto_grant",
    )
    session.add(grant)
    return req, grant


def issue_approval_grant(
    session: Session,
    *,
    req: PermissionRequest,
    workflow_id: str,
    reviewer_user_id: str,
    request_policy: dict[str, Any] | None,
    review_reason: str | None = None,
    origin: str = "approval",
) -> WorkflowGrant:
    """Approve 路径：调用方已 CAS request→approved；此处写 grant。"""
    policy = normalize_request_policy(request_policy)
    now = datetime.utcnow()
    req.reviewed_by = reviewer_user_id
    req.reviewed_at = now
    req.review_reason = review_reason
    req.updated_at = now
    grant = WorkflowGrant(
        id=str(uuid.uuid4()),
        tenant_id=req.tenant_id,
        request_id=req.id,
        workflow_id=workflow_id,
        scope=str(policy["scope"]),
        applicant_user_id=req.applicant_user_id,
        caps=[
            cap_entry(
                capability_id=req.capability_id,
                permission=req.needed_perm,
            )
        ],
        issued_at=now,
        expires_at=now + timedelta(days=int(policy["default_ttl_days"])),
        revoked_at=None,
        origin=origin,
    )
    session.add(grant)
    return grant


def renew_grant(
    session: Session,
    *,
    grant: WorkflowGrant,
    request_policy: dict[str, Any] | None,
    now: datetime | None = None,
) -> WorkflowGrant | None:
    """E3.2 — auto_renew：同 scope/ttl 签发新 grant；幂等键 origin=renew:{old_id}。

    调用方须已持有行级锁 / 确认 grant 仍 active 且未 revoked。
    """
    now = now or datetime.utcnow()
    if grant.revoked_at is not None:
        return None
    policy = normalize_request_policy(request_policy)
    if not policy.get("auto_renew"):
        return None
    renew_origin = f"renew:{grant.id}"
    if len(renew_origin) > 80:
        renew_origin = f"r:{grant.id.replace('-', '')}"
    existing = (
        session.query(WorkflowGrant)
        .filter(
            WorkflowGrant.tenant_id == grant.tenant_id,
            WorkflowGrant.origin == renew_origin,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing  # 幂等：已续过

    old_req = (
        session.query(PermissionRequest)
        .filter(PermissionRequest.id == grant.request_id)
        .one_or_none()
    )
    cap0 = (grant.caps or [{}])[0] if isinstance(grant.caps, list) else {}
    capability_id = str(
        (cap0.get("capability_id") if isinstance(cap0, dict) else None)
        or (old_req.capability_id if old_req else "")
        or ""
    )
    permission = str(
        (cap0.get("permission") if isinstance(cap0, dict) else None)
        or (old_req.needed_perm if old_req else "")
        or ""
    )
    org_unit_id = (old_req.org_unit_id if old_req else "") or ""
    run_id = (old_req.run_id if old_req else "") or f"renew-{grant.id}"
    node_id = (old_req.node_id if old_req else "") or "renew"

    ttl = int(policy["default_ttl_days"])
    req = PermissionRequest(
        id=str(uuid.uuid4()),
        tenant_id=grant.tenant_id,
        run_id=run_id,
        node_id=node_id,
        applicant_user_id=grant.applicant_user_id,
        needed_perm=permission or "renewed",
        org_unit_id=org_unit_id or "unknown",
        capability_id=capability_id or "renewed",
        status="auto_approved",
        reviewed_by="system:auto_renew",
        reviewed_at=now,
        review_reason=f"auto_renew_from:{grant.id}",
        approval_note=None,
        requestable_mode=(old_req.requestable_mode if old_req else "true") or "true",
        created_at=now,
        updated_at=now,
    )
    session.add(req)
    session.flush()
    new_grant = WorkflowGrant(
        id=str(uuid.uuid4()),
        tenant_id=grant.tenant_id,
        request_id=req.id,
        workflow_id=grant.workflow_id,
        scope=str(policy["scope"]),
        applicant_user_id=grant.applicant_user_id,
        caps=list(grant.caps) if isinstance(grant.caps, list) else [
            cap_entry(capability_id=capability_id, permission=permission)
        ],
        issued_at=now,
        expires_at=now + timedelta(days=ttl),
        revoked_at=None,
        origin=renew_origin,
    )
    session.add(new_grant)
    from packages.audit import write_audit_sync

    write_audit_sync(
        {
            "tenant_id": grant.tenant_id,
            "user_id": grant.applicant_user_id,
            "action": "renew",
            "trace_id": run_id,
            "input_text": "",
            "output_text": f"from={grant.id}:to={new_grant.id}:ttl={ttl}",
            "model": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
            "latency_ms": 0.0,
            "error_code": None,
            "ip_address": "",
            "user_agent": "",
            "credential_kind": "delegation",
            "key_id": None,
            "run_id": run_id,
            "node_id": node_id,
            "created_at": now,
        }
    )
    return new_grant


def scan_grants_for_auto_renew(
    *,
    within_days: int = 7,
    now: datetime | None = None,
    limit: int = 100,
) -> dict[str, int]:
    """主动日扫：expires_at <= now+within_days 且未 revoked → 按 workflow.request_policy 续期。

    行级 ``FOR UPDATE SKIP LOCKED`` 防多副本双续。
    """
    from sqlalchemy import text

    from packages.database.pgvector_session import Workflow, get_pg_session

    now = now or datetime.utcnow()
    horizon = now + timedelta(days=within_days)
    renewed = 0
    skipped = 0
    expired_marked = 0
    sf = get_pg_session()
    with sf.Session() as session:
        # advisory lock: 单扫描领导者（进程间）
        locked = session.execute(
            text("SELECT pg_try_advisory_lock(:k)"),
            {"k": 41030215},
        ).scalar()
        if not locked:
            return {"renewed": 0, "skipped": 0, "expired_marked": 0, "lock": 0}
        try:
            rows = session.execute(
                text(
                    """
                    SELECT id FROM workflow_grants
                    WHERE revoked_at IS NULL
                      AND expires_at <= :horizon
                      AND expires_at > :now
                    ORDER BY expires_at ASC
                    LIMIT :lim
                    FOR UPDATE SKIP LOCKED
                    """
                ),
                {"horizon": horizon, "now": now, "lim": limit},
            ).fetchall()
            for (gid,) in rows:
                grant = (
                    session.query(WorkflowGrant)
                    .filter(WorkflowGrant.id == gid)
                    .one_or_none()
                )
                if grant is None or grant.revoked_at is not None:
                    skipped += 1
                    continue
                wf = (
                    session.query(Workflow)
                    .filter(
                        Workflow.id == grant.workflow_id,
                        Workflow.tenant_id == grant.tenant_id,  # 拍板 08-15:纵深防御,防跨租户读 policy
                    )
                    .one_or_none()
                )
                policy = normalize_request_policy(
                    dict(wf.request_policy) if wf and wf.request_policy else None
                )
                if policy.get("auto_renew"):
                    ng = renew_grant(
                        session, grant=grant, request_policy=policy, now=now
                    )
                    if ng is not None and ng.id != grant.id:
                        renewed += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
            session.commit()
        finally:
            session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": 41030215})
    return {
        "renewed": renewed,
        "skipped": skipped,
        "expired_marked": expired_marked,
        "lock": 1,
    }


def can_review_request(
    tenant: TenantContext,
    org_scope: OrgScope,
    *,
    req: PermissionRequest,
    session: Session | None = None,
) -> bool:
    """实时资格：敏感仅 admin；否则 dept_manager(org) 或 admin；升级后原经理仍可批。"""
    mode: RequestableMode
    raw = (req.requestable_mode or "true").strip()
    if raw not in ("true", "sensitive", "false"):
        mode = "true"
    else:
        mode = raw  # type: ignore[assignment]
    if mode == "false":
        return False
    return is_eligible_approver(
        tenant,
        org_scope,
        resource_org_unit_id=req.org_unit_id,
        requestable_mode=mode,
        session=session,
    )


def expire_stale_approvals_for_node(
    session: Session,
    *,
    tenant_id: str,
    workflow_id: str,
    run_id: str,
    node_id: str,
    applicant_user_id: str,
    capability_id: str,
    now: datetime | None = None,
) -> int:
    """
    Grant TTL 过期 → 关联 request 标 expired（审计保留旧周期）。
    返回新标 expired 条数；调用方随后 create_pending_request 开新周期。
    """
    now = now or datetime.utcnow()
    n = 0
    grants = (
        session.query(WorkflowGrant)
        .filter(
            WorkflowGrant.tenant_id == tenant_id,
            WorkflowGrant.workflow_id == workflow_id,
            WorkflowGrant.applicant_user_id == applicant_user_id,
            WorkflowGrant.revoked_at.is_(None),
            WorkflowGrant.expires_at <= now,
        )
        .all()
    )
    for g in grants:
        if not caps_cover(g.caps, capability_id=capability_id):
            continue
        req = (
            session.query(PermissionRequest)
            .filter(PermissionRequest.id == g.request_id)
            .one_or_none()
        )
        if req is None or req.status not in ("approved", "auto_approved"):
            continue
        # 同 capability 的历史批准进入 expired（保留审计）
        req.status = "expired"
        req.updated_at = now
        reason = (req.review_reason or "").strip()
        req.review_reason = (
            f"{reason};grant_ttl_expired" if reason else "grant_ttl_expired"
        )
        n += 1
        from packages.audit import write_audit_sync

        write_audit_sync(
            {
                "tenant_id": tenant_id,
                "user_id": applicant_user_id,
                "action": "workflow.hang.request_expired",
                "trace_id": run_id,
                "input_text": "",
                "output_text": f"request={req.id}:grant={g.id}:node={node_id}",
                "model": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "latency_ms": 0.0,
                "error_code": None,
                "ip_address": "",
                "user_agent": "",
                "credential_kind": "delegation",
                "key_id": None,
                "run_id": run_id,
                "node_id": node_id,
                "created_at": now,
            }
        )
        # TTL 过期重申请 → 审批人（相关方）；新 pending 由调用方 create
        try:
            from packages.notification.service import (
                list_tenant_admin_user_ids,
                notify_many,
            )
            from packages.workflow.notify import resolve_hang_route

            route = resolve_hang_route(
                session,
                tenant_id=tenant_id,
                org_unit_id=req.org_unit_id,
            )
            targets = (
                list_tenant_admin_user_ids(session, tenant_id)
                if route.escalate_to_tenant_admin
                else list(route.manager_user_ids)
            )
            notify_many(
                tenant_id,
                targets,
                "hang.ttl_reapply",
                {
                    "run_id": run_id,
                    "node_id": node_id,
                    "request_id": req.id,
                    "grant_id": g.id,
                    "capability_id": capability_id,
                },
            )
        except Exception:
            pass
    return n


def create_pending_request(
    session: Session,
    *,
    tenant_id: str,
    run_id: str,
    node_id: str,
    applicant_user_id: str,
    needed_perm: str,
    org_unit_id: str,
    capability_id: str,
    requestable_mode: RequestableMode,
    approval_note: str | None,
) -> PermissionRequest:
    now = datetime.utcnow()
    req = PermissionRequest(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        run_id=run_id,
        node_id=node_id,
        applicant_user_id=applicant_user_id,
        needed_perm=needed_perm,
        org_unit_id=org_unit_id,
        capability_id=capability_id,
        status="pending",
        approval_note=approval_note,
        requestable_mode=requestable_mode,
        created_at=now,
        updated_at=now,
    )
    session.add(req)
    return req
