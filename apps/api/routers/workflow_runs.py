"""Workflow run API — Wave D4."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.core.errors import ErrorCode
from packages.org.scope import assert_org_access, resolve_org_scope, visible_org_filter
from backend.database.pgvector_session import Workflow, WorkflowRun, WorkflowRunNode, get_pg_session
from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from packages.workflow import runner as run_svc

router = APIRouter(tags=["workflow-runs"])


def _scope(session: Session, tenant: TenantContext):
    return resolve_org_scope(
        session,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        platform_role=tenant.role,
        is_cross_tenant=tenant.is_cross_tenant,
    )


def _run_dict(
    run: WorkflowRun,
    *,
    workflow_name: str | None = None,
    workflow_status: str | None = None,
    parent_status: str | None = None,
) -> dict[str, Any]:
    # 7A: parent failed/cancelled → child marked orphan (incl. after child finishes)
    orphan = bool(
        run.parent_run_id
        and parent_status in ("failed", "cancelled")
    )
    return {
        "id": run.id,
        "tenant_id": run.tenant_id,
        "workflow_id": run.workflow_id,
        "workflow_name": workflow_name,
        "workflow_status": workflow_status,
        "org_unit_id": run.org_unit_id,
        "status": run.status,
        "workflow_version": run.workflow_version,
        "workflow_revision": run.workflow_revision,
        "acting_user_id": run.acting_user_id,
        "credential_kind": run.credential_kind,
        "parent_run_id": run.parent_run_id,
        "parent_node_id": getattr(run, "parent_node_id", None),
        "composition_depth": getattr(run, "composition_depth", 0) or 0,
        "orphan": orphan,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _parent_statuses(session: Session, runs: list[WorkflowRun]) -> dict[str, str]:
    pids = {r.parent_run_id for r in runs if r.parent_run_id}
    if not pids:
        return {}
    rows = (
        session.query(WorkflowRun.id, WorkflowRun.status)
        .filter(WorkflowRun.id.in_(pids))
        .all()
    )
    return {rid: st for rid, st in rows}


@router.post("/workflows/{workflow_id}/runs")
async def start_workflow_run(
    workflow_id: str,
    body: dict[str, Any] | None = Body(default=None),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    payload = body or {}
    if payload.get("parent_run_id") is not None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PARENT_FORGED",
                "message": "client_cannot_set_parent_run_id",
            },
        )
    run_inputs = payload.get("input")
    if run_inputs is not None and not isinstance(run_inputs, dict):
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_INPUT", "message": "input_must_be_object"},
        )
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        started = run_svc.start_run(
            session,
            tenant=tenant,
            org_scope=scope,
            workflow_id=workflow_id,
            run_inputs=run_inputs if isinstance(run_inputs, dict) else None,
        )
    run_svc.schedule_execute(started["id"])
    return started


@router.post("/runs/{run_id}/execute")
async def execute_run_endpoint(
    run_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    """Explicit re-entry; waiting_child → 409 (R-H)."""
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        run = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.tenant_id == tenant.tenant_id, WorkflowRun.id == run_id)
            .one_or_none()
        )
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={"code": ErrorCode.RUN_NOT_FOUND, "message": "run_not_found"},
            )
        assert_org_access(scope, run.org_unit_id, session=session)
        waiting = (
            session.query(WorkflowRunNode)
            .filter(
                WorkflowRunNode.run_id == run_id,
                WorkflowRunNode.status == "waiting_child",
            )
            .first()
        )
        if waiting is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "WAITING_CHILD",
                    "message": "run_waiting_on_child",
                    "node_id": waiting.node_id,
                },
            )
    run_svc.schedule_execute(run_id)
    return {"id": run_id, "scheduled": True}


@router.get("/runs/{run_id}/children")
async def list_run_children(
    run_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        parent = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.tenant_id == tenant.tenant_id, WorkflowRun.id == run_id)
            .one_or_none()
        )
        if parent is None:
            raise HTTPException(
                status_code=404,
                detail={"code": ErrorCode.RUN_NOT_FOUND, "message": "run_not_found"},
            )
        assert_org_access(scope, parent.org_unit_id, session=session)
        kids = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.parent_run_id == run_id)
            .order_by(WorkflowRun.created_at.asc())
            .all()
        )
        return {
            "run_id": run_id,
            "items": [
                _run_dict(k, parent_status=parent.status) for k in kids
            ],
        }


@router.get("/runs")
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        q = session.query(WorkflowRun, Workflow).outerjoin(
            Workflow, Workflow.id == WorkflowRun.workflow_id
        ).filter(WorkflowRun.tenant_id == tenant.tenant_id)
        if status:
            q = q.filter(WorkflowRun.status == status)
        filt = visible_org_filter(scope)
        if filt["mode"] != "tenant":
            unit_ids = set(filt.get("unit_ids") or set())
            q = q.filter(WorkflowRun.org_unit_id.in_(unit_ids))
        rows = (
            q.order_by(WorkflowRun.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        runs_only = [run for run, _wf in rows]
        pstat = _parent_statuses(session, runs_only)
        items = [
            _run_dict(
                run,
                workflow_name=wf.name if wf else None,
                workflow_status=wf.status if wf else None,
                parent_status=pstat.get(run.parent_run_id or ""),
            )
            for run, wf in rows
        ]
        return {"items": items, "limit": limit, "offset": offset}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        run = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.tenant_id == tenant.tenant_id, WorkflowRun.id == run_id)
            .one_or_none()
        )
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={"code": ErrorCode.RUN_NOT_FOUND, "message": "run_not_found"},
            )
        assert_org_access(scope, run.org_unit_id, session=session)
        wf = (
            session.query(Workflow)
            .filter(Workflow.id == run.workflow_id)
            .one_or_none()
        )
        parent_status = None
        if run.parent_run_id:
            prow = (
                session.query(WorkflowRun.status)
                .filter(WorkflowRun.id == run.parent_run_id)
                .one_or_none()
            )
            parent_status = prow[0] if prow else None
        out = _run_dict(
            run,
            workflow_name=wf.name if wf else None,
            workflow_status=wf.status if wf else None,
            parent_status=parent_status,
        )
        if run.status == "suspended":
            from packages.workflow.notify import hang_visibility

            out.update(hang_visibility(session, run_id=run.id))
        return out


@router.post("/workflows/{workflow_id}/schedules")
async def create_workflow_schedule(
    workflow_id: str,
    body: dict[str, Any] | None = Body(default=None),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    """I6：创建 cron；created_by 从 auth 钉死，忽略/拒 body.created_by。"""
    from packages.workflow.scheduler import create_scheduled_run

    payload = body or {}
    body_cb = payload.get("created_by")
    if body_cb is not None and str(body_cb) != str(tenant.user_id):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CREATED_BY_FORGED",
                "message": "created_by_must_match_auth",
            },
        )
    cron = str(payload.get("cron") or "").strip()
    if not cron:
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_CRON", "message": "cron_required"},
        )
    run_inputs = payload.get("input") or payload.get("run_inputs")
    if run_inputs is not None and not isinstance(run_inputs, dict):
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_INPUT", "message": "input_must_be_object"},
        )
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        wf = (
            session.query(Workflow)
            .filter(Workflow.tenant_id == tenant.tenant_id, Workflow.id == workflow_id)
            .one_or_none()
        )
        if wf is None:
            raise HTTPException(
                status_code=404,
                detail={"code": ErrorCode.WF_NOT_FOUND, "message": "workflow_not_found"},
            )
        assert_org_access(scope, wf.org_unit_id, session=session)
        try:
            row = create_scheduled_run(
                session,
                tenant_id=tenant.tenant_id,
                workflow_id=workflow_id,
                cron=cron,
                created_by=tenant.user_id,
                run_inputs=run_inputs if isinstance(run_inputs, dict) else None,
                enabled=bool(payload.get("enabled", True)),
            )
            session.commit()
        except ValueError as exc:
            session.rollback()
            raise HTTPException(
                status_code=400,
                detail={"code": "BAD_SCHEDULE", "message": str(exc)},
            ) from exc
        return {
            "id": row.id,
            "workflow_id": row.workflow_id,
            "cron": row.cron,
            "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
            "created_by": row.created_by,
            "enabled": row.enabled,
        }


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        return run_svc.cancel_run(
            session, tenant=tenant, org_scope=scope, run_id=run_id
        )


@router.get("/runs/{run_id}/nodes")
async def get_run_nodes(
    run_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        run = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.tenant_id == tenant.tenant_id, WorkflowRun.id == run_id)
            .one_or_none()
        )
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={"code": ErrorCode.RUN_NOT_FOUND, "message": "run_not_found"},
            )
        assert_org_access(scope, run.org_unit_id, session=session)
        nodes = (
            session.query(WorkflowRunNode)
            .filter(WorkflowRunNode.run_id == run_id)
            .order_by(WorkflowRunNode.started_at.asc().nullsfirst())
            .all()
        )
        return {
            "run_id": run_id,
            "items": [
                {
                    "id": n.id,
                    "node_id": n.node_id,
                    "status": n.status,
                    "attempt": n.attempt,
                    "output": n.output_json,
                    "evidence": (n.output_json or {}).get("evidence")
                    if isinstance(n.output_json, dict)
                    else [],
                    "error_message": n.error_message,
                    "started_at": n.started_at.isoformat() if n.started_at else None,
                    "finished_at": n.finished_at.isoformat() if n.finished_at else None,
                }
                for n in nodes
            ],
        }
