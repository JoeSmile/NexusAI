"""Workflow definition API — Wave C2."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from packages.org.scope import resolve_org_scope
from backend.database.pgvector_session import get_pg_session
from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from packages.workflow import service as wf_svc
from packages.workflow.models import WorkflowCreateBody, WorkflowPatchBody

router = APIRouter(prefix="/workflows", tags=["workflows"])


class PublishBody(BaseModel):
    base_revision: int | None = Field(None, ge=0)
    intent_tags: list[str] | None = None


def _scope(session, tenant: TenantContext):
    return resolve_org_scope(
        session,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        platform_role=tenant.role,
        is_cross_tenant=tenant.is_cross_tenant,
    )


@router.post("")
async def create_workflow(
    body: WorkflowCreateBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        return wf_svc.create_workflow(
            session,
            tenant=tenant,
            org_scope=scope,
            name=body.name,
            org_unit_id=body.org_unit_id,
            ir_data=body.ir,
        )


@router.get("")
async def list_workflows(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        items = wf_svc.list_workflows(
            session,
            tenant=tenant,
            org_scope=scope,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {"items": items, "limit": limit, "offset": offset}


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        return wf_svc.get_workflow(
            session, tenant=tenant, org_scope=scope, workflow_id=workflow_id
        )


@router.patch("/{workflow_id}")
async def patch_workflow(
    workflow_id: str,
    body: WorkflowPatchBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        return wf_svc.patch_workflow(
            session,
            tenant=tenant,
            org_scope=scope,
            workflow_id=workflow_id,
            base_revision=body.base_revision,
            name=body.name,
            ir_data=body.ir,
            org_unit_id=body.org_unit_id,
            request_policy=body.request_policy,
        )


@router.post("/{workflow_id}/publish")
async def publish_workflow(
    workflow_id: str,
    body: PublishBody | None = None,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        br = body.base_revision if body else None
        tags = body.intent_tags if body else None
        return wf_svc.publish_workflow(
            session,
            tenant=tenant,
            org_scope=scope,
            workflow_id=workflow_id,
            base_revision=br,
            intent_tags=tags,
        )


@router.post("/{workflow_id}/fork-draft")
async def fork_draft(
    workflow_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        return wf_svc.fork_draft(
            session, tenant=tenant, org_scope=scope, workflow_id=workflow_id
        )


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    sf = get_pg_session()
    with sf.Session() as session:
        scope = _scope(session, tenant)
        return wf_svc.delete_workflow(
            session, tenant=tenant, org_scope=scope, workflow_id=workflow_id
        )
