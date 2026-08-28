"""Workflow hang-wait approvals API (Wave E4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.audit import write_audit_sync
from packages.org.scope import OrgScope, assert_org_access, resolve_org_scope
from backend.database.pgvector_session import (
    PermissionRequest,
    Workflow,
    WorkflowRun,
    get_pg_session,
)
from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from packages.workflow import runner as run_svc
from packages.workflow.grants import can_review_request, issue_approval_grant
from packages.workflow.notify import maybe_escalate_timeout

router = APIRouter(prefix="/workflow-approvals", tags=["workflow-approvals"])


class ApproveBody(BaseModel):
    reason: str | None = None
    # manager 确认时可改；缺省用 workflow.request_policy
    scope: str | None = Field(default=None, pattern="^(single|recurring)$")
    ttl_days: int | None = Field(default=None, ge=1, le=3650)


class RejectBody(BaseModel):
    reason: str | None = None


class BatchBody(BaseModel):
    run_id: str
    action: str = Field(..., pattern="^(approve|reject)$")
    note: str | None = None


def _pending_count(session: Session, *, run_id: str, tenant_id: str) -> int:
    return (
        session.query(PermissionRequest)
        .filter(
            PermissionRequest.tenant_id == tenant_id,
            PermissionRequest.run_id == run_id,
            PermissionRequest.status == "pending",
        )
        .count()
    )


def _scope(session: Session, tenant: TenantContext) -> OrgScope:
    return resolve_org_scope(
        session,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        platform_role=tenant.role,
        is_cross_tenant=tenant.is_cross_tenant,
    )


def _req_dict(req: PermissionRequest, *, workflow_name: str | None = None) -> dict[str, Any]:
    return {
        "id": req.id,
        "tenant_id": req.tenant_id,
        "run_id": req.run_id,
        "node_id": req.node_id,
        "applicant_user_id": req.applicant_user_id,
        "needed_perm": req.needed_perm,
        "org_unit_id": req.org_unit_id,
        "capability_id": req.capability_id,
        "status": req.status,
        "requestable_mode": req.requestable_mode,
        "approval_note": req.approval_note,
        "escalated_at": req.escalated_at.isoformat() if req.escalated_at else None,
        "reviewed_by": req.reviewed_by,
        "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
        "review_reason": req.review_reason,
        "workflow_name": workflow_name,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }


def _audit(
    *,
    tenant_id: str,
    user_id: str,
    action: str,
    run_id: str | None,
    node_id: str | None,
    output_text: str = "",
) -> None:
    write_audit_sync(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": action,
            "trace_id": run_id or "",
            "input_text": "",
            "output_text": output_text[:500],
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
            "created_at": datetime.utcnow(),
        }
    )


@router.get("/inbox")
async def inbox(
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        rows = (
            session.query(PermissionRequest)
            .filter(
                PermissionRequest.tenant_id == tenant.tenant_id,
                PermissionRequest.status == "pending",
            )
            .order_by(PermissionRequest.created_at.asc())
            .all()
        )
        items: list[dict[str, Any]] = []
        dirty = False
        for req in rows:
            if maybe_escalate_timeout(session, req):
                dirty = True
            if not can_review_request(tenant, scope, req=req, session=session):
                continue
            # 资源范围：非全租户必须在 org 内
            try:
                assert_org_access(scope, req.org_unit_id, session=session)
            except HTTPException:
                continue
            run = (
                session.query(WorkflowRun)
                .filter(WorkflowRun.id == req.run_id)
                .one_or_none()
            )
            wf_name = None
            if run is not None:
                wf = (
                    session.query(Workflow)
                    .filter(Workflow.id == run.workflow_id)
                    .one_or_none()
                )
                wf_name = wf.name if wf else None
            items.append(_req_dict(req, workflow_name=wf_name))
        if dirty:
            session.commit()
        return {"items": items}


@router.post("/batch")
async def batch_review(
    body: BatchBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    """E3.1 — run 级一键审批；逐条 try；仅无剩余 pending 缺权时 resume。"""
    sf = get_pg_session()
    results: list[dict[str, Any]] = []
    run_id = body.run_id
    with sf.Session() as session:
        scope = _scope(session, tenant)
        run = (
            session.query(WorkflowRun)
            .filter(
                WorkflowRun.id == run_id,
                WorkflowRun.tenant_id == tenant.tenant_id,
            )
            .one_or_none()
        )
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "RUN_404", "message": "run_not_found"},
            )
        pending = (
            session.query(PermissionRequest)
            .filter(
                PermissionRequest.tenant_id == tenant.tenant_id,
                PermissionRequest.run_id == run_id,
                PermissionRequest.status == "pending",
            )
            .order_by(PermissionRequest.created_at.asc())
            .all()
        )
        wf = (
            session.query(Workflow)
            .filter(Workflow.id == run.workflow_id)
            .one_or_none()
        )
        policy = dict(wf.request_policy) if wf and wf.request_policy else {}

        for req in pending:
            item: dict[str, Any] = {"request_id": req.id, "node_id": req.node_id}
            try:
                if not can_review_request(tenant, scope, req=req, session=session):
                    item.update({"ok": False, "skipped": True, "reason": "not_eligible"})
                    results.append(item)
                    continue
                try:
                    assert_org_access(scope, req.org_unit_id, session=session)
                except HTTPException:
                    item.update({"ok": False, "skipped": True, "reason": "org_denied"})
                    results.append(item)
                    continue

                nested = session.begin_nested()
                try:
                    if body.action == "approve":
                        res = session.execute(
                            text(
                                "UPDATE permission_requests SET status='approved', "
                                "updated_at=:now WHERE id=:id AND status='pending'"
                            ),
                            {"id": req.id, "now": datetime.utcnow()},
                        )
                        if res.rowcount != 1:
                            nested.rollback()
                            item.update(
                                {
                                    "ok": False,
                                    "skipped": True,
                                    "reason": "already_resolved",
                                }
                            )
                            results.append(item)
                            continue
                        session.refresh(req)
                        origin = (
                            "self_approve"
                            if req.applicant_user_id == tenant.user_id
                            else "approval"
                        )
                        grant = issue_approval_grant(
                            session,
                            req=req,
                            workflow_id=run.workflow_id,
                            reviewer_user_id=tenant.user_id,
                            request_policy=policy,
                            review_reason=body.note,
                            origin=origin,
                        )
                        session.flush()
                        _audit(
                            tenant_id=tenant.tenant_id,
                            user_id=tenant.user_id,
                            action="batch_approve",
                            run_id=run_id,
                            node_id=req.node_id,
                            output_text=(body.note or f"grant={grant.id}")[:500],
                        )
                        nested.commit()
                        item.update(
                            {
                                "ok": True,
                                "status": "approved",
                                "grant_id": grant.id,
                            }
                        )
                    else:
                        res = session.execute(
                            text(
                                "UPDATE permission_requests SET status='rejected', "
                                "reviewed_by=:uid, reviewed_at=:now, review_reason=:reason, "
                                "updated_at=:now WHERE id=:id AND status='pending'"
                            ),
                            {
                                "id": req.id,
                                "uid": tenant.user_id,
                                "now": datetime.utcnow(),
                                "reason": (body.note or "batch_rejected")[:500],
                            },
                        )
                        if res.rowcount != 1:
                            nested.rollback()
                            item.update(
                                {
                                    "ok": False,
                                    "skipped": True,
                                    "reason": "already_resolved",
                                }
                            )
                            results.append(item)
                            continue
                        session.execute(
                            text(
                                "UPDATE workflow_runs SET status='failed', "
                                "error_code='AUTH_002', "
                                "error_message='permission_rejected', "
                                "finished_at=:now, updated_at=:now "
                                "WHERE id=:id AND status='suspended'"
                            ),
                            {"id": run_id, "now": datetime.utcnow()},
                        )
                        _audit(
                            tenant_id=tenant.tenant_id,
                            user_id=tenant.user_id,
                            action="batch_reject",
                            run_id=run_id,
                            node_id=req.node_id,
                            output_text=(body.note or "batch_rejected")[:200],
                        )
                        nested.commit()
                        item.update({"ok": True, "status": "rejected"})
                    results.append(item)
                except Exception as exc:
                    nested.rollback()
                    item.update({"ok": False, "error": str(exc)[:200]})
                    results.append(item)
            except Exception as exc:
                item.update({"ok": False, "error": str(exc)[:200]})
                results.append(item)

        remaining = _pending_count(
            session, run_id=run_id, tenant_id=tenant.tenant_id
        )
        session.commit()

    resumed = False
    if body.action == "approve" and remaining == 0:
        run_svc.schedule_resume(run_id)
        resumed = True

    return {
        "ok": True,
        "run_id": run_id,
        "action": body.action,
        "results": results,
        "pending_remaining": remaining,
        "resumed": resumed,
    }


@router.post("/{request_id}/approve")
async def approve(
    request_id: str,
    body: ApproveBody | None = None,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    body = body or ApproveBody()
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        req = (
            session.query(PermissionRequest)
            .filter(
                PermissionRequest.tenant_id == tenant.tenant_id,
                PermissionRequest.id == request_id,
            )
            .one_or_none()
        )
        if req is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "APR_404", "message": "request_not_found"},
            )
        if not can_review_request(tenant, scope, req=req, session=session):
            raise HTTPException(
                status_code=403,
                detail={"code": "APR_403", "message": "not_eligible_approver"},
            )
        assert_org_access(scope, req.org_unit_id, session=session)

        res = session.execute(
            text(
                "UPDATE permission_requests SET status='approved', updated_at=:now "
                "WHERE id=:id AND status='pending'"
            ),
            {"id": request_id, "now": datetime.utcnow()},
        )
        if res.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail={"code": "APR_409", "message": "already_resolved"},
            )
        session.refresh(req)

        run = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.id == req.run_id)
            .one_or_none()
        )
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "RUN_404", "message": "run_not_found"},
            )
        wf = (
            session.query(Workflow)
            .filter(Workflow.id == run.workflow_id)
            .one_or_none()
        )
        policy = dict(wf.request_policy) if wf and wf.request_policy else {}
        if body.scope:
            policy["scope"] = body.scope
        if body.ttl_days:
            policy["default_ttl_days"] = body.ttl_days

        origin = (
            "self_approve" if req.applicant_user_id == tenant.user_id else "approval"
        )
        grant = issue_approval_grant(
            session,
            req=req,
            workflow_id=run.workflow_id,
            reviewer_user_id=tenant.user_id,
            request_policy=policy,
            review_reason=body.reason,
            origin=origin,
        )
        session.commit()

        action = (
            "workflow.approve.self"
            if req.applicant_user_id == tenant.user_id
            else "workflow.approve"
        )
        run_id = req.run_id
        grant_id = grant.id
        node_id = req.node_id
        applicant_user_id = req.applicant_user_id
        _audit(
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            action=action,
            run_id=run_id,
            node_id=node_id,
            output_text=f"grant={grant_id}:cap={req.capability_id}",
        )

    # 批 → 申请人（self_approve 不另发用户通知，对齐 auto-grant 只审计）
    try:
        if action == "workflow.approve":
            from packages.notification.service import notify

            notify(
                tenant.tenant_id,
                applicant_user_id,
                "hang.approved",
                {
                    "run_id": run_id,
                    "node_id": node_id,
                    "request_id": request_id,
                    "grant_id": grant_id,
                },
            )
    except Exception:
        pass

    run_svc.schedule_resume(run_id)
    return {
        "ok": True,
        "request_id": request_id,
        "grant_id": grant_id,
        "run_id": run_id,
        "status": "approved",
    }


@router.post("/{request_id}/reject")
async def reject(
    request_id: str,
    body: RejectBody | None = None,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    body = body or RejectBody()
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        req = (
            session.query(PermissionRequest)
            .filter(
                PermissionRequest.tenant_id == tenant.tenant_id,
                PermissionRequest.id == request_id,
            )
            .one_or_none()
        )
        if req is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "APR_404", "message": "request_not_found"},
            )
        if not can_review_request(tenant, scope, req=req, session=session):
            raise HTTPException(
                status_code=403,
                detail={"code": "APR_403", "message": "not_eligible_approver"},
            )
        assert_org_access(scope, req.org_unit_id, session=session)

        res = session.execute(
            text(
                "UPDATE permission_requests SET status='rejected', "
                "reviewed_by=:uid, reviewed_at=:now, review_reason=:reason, updated_at=:now "
                "WHERE id=:id AND status='pending'"
            ),
            {
                "id": request_id,
                "uid": tenant.user_id,
                "now": datetime.utcnow(),
                "reason": (body.reason or "rejected")[:500],
            },
        )
        if res.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail={"code": "APR_409", "message": "already_resolved"},
            )

        # CAS: 仅 suspended → failed（评审 M-1）——已被并发 resume/cancel 的 run 不动
        session.execute(
            text(
                "UPDATE workflow_runs SET status='failed', error_code='AUTH_002', "
                "error_message='permission_rejected', finished_at=:now, updated_at=:now "
                "WHERE id=:id AND status='suspended'"
            ),
            {"id": req.run_id, "now": datetime.utcnow()},
        )
        session.commit()
        run_id = req.run_id
        node_id = req.node_id
        applicant_user_id = req.applicant_user_id
        _audit(
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            action="workflow.reject",
            run_id=run_id,
            node_id=node_id,
            output_text=(body.reason or "rejected")[:200],
        )
    try:
        from packages.notification.service import notify

        notify(
            tenant.tenant_id,
            applicant_user_id,
            "hang.rejected",
            {
                "run_id": run_id,
                "node_id": node_id,
                "request_id": request_id,
            },
        )
    except Exception:
        pass
    return {"ok": True, "request_id": request_id, "status": "rejected"}
