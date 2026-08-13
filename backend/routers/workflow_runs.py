"""Workflow run API — Wave D4."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.auth.models import TenantContext
from backend.core.errors import ErrorCode
from backend.core.org.scope import assert_org_access, resolve_org_scope, visible_org_filter
from backend.core.workflow import runner as run_svc
from backend.database.pgvector_session import Workflow, WorkflowRun, WorkflowRunNode, get_pg_session

router = APIRouter(tags=["workflow-runs"])


def _scope(session: Session, tenant: TenantContext):
    return resolve_org_scope(
        session,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        platform_role=tenant.role,
        is_cross_tenant=tenant.is_cross_tenant,
    )


def _run_dict(run: WorkflowRun, *, workflow_name: str | None = None, workflow_status: str | None = None) -> dict[str, Any]:
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
        "error_code": run.error_code,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.post("/workflows/{workflow_id}/runs")
async def start_workflow_run(
    workflow_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        started = run_svc.start_run(
            session,
            tenant=tenant,
            org_scope=scope,
            workflow_id=workflow_id,
        )
    run_svc.schedule_execute(started["id"])
    return started


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
        items = [
            _run_dict(run, workflow_name=wf.name if wf else None, workflow_status=wf.status if wf else None)
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
        return _run_dict(
            run,
            workflow_name=wf.name if wf else None,
            workflow_status=wf.status if wf else None,
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
