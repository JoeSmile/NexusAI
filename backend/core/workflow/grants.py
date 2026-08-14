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

from backend.core.auth.models import TenantContext
from backend.core.org.scope import OrgScope, assert_org_access
from backend.core.workflow.security_gates import RequestableMode
from backend.database.pgvector_session import PermissionRequest, WorkflowGrant

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
    from backend.database.pgvector_session import get_pg_session

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
        from backend.core.audit import write_audit_sync

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
