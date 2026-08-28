"""Wave E4 — approve → grant → resume."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from packages.auth.models import TenantContext
from packages.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
)
from packages.capability.registry import CapabilityRegistry
from backend.core.org.scope import OrgScope
from packages.workflow.grants import issue_approval_grant
from packages.workflow.runner import execute_run, resume_run, start_run
from backend.database.pgvector_session import (
    PermissionRequest,
    Workflow,
    WorkflowGrant,
    WorkflowRun,
    WorkflowRunNode,
    get_pg_session,
)


async def _fake_invoke(cap_id, params, tenant):
    yield {"event": "token", "data": "ok"}
    yield {"event": "done", "data": {"sources": []}}


def _cleanup(session, tid: str, run_id: str) -> None:
    session.query(WorkflowGrant).filter(WorkflowGrant.tenant_id == tid).delete()
    session.query(PermissionRequest).filter(PermissionRequest.tenant_id == tid).delete()
    session.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == run_id).delete()
    session.query(WorkflowRun).filter(WorkflowRun.id == run_id).delete()
    session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
    session.commit()


@pytest.mark.asyncio
async def test_resume_after_grant(monkeypatch):
    tid = f"e4-r-{uuid.uuid4().hex[:8]}"
    uid = f"user_{uuid.uuid4().hex[:6]}"
    mgr = f"mgr_{uuid.uuid4().hex[:6]}"
    sf = get_pg_session()
    reg = CapabilityRegistry()
    reg.register(
        CapabilitySpec(
            id="kb-tool",
            name="KB",
            kind=CapabilityKind.TOOL,
            provider=CapabilityProvider.NEXUSAI,
            spec={"governance": True, "leaf": True},
            permission="kb:read",
        )
    )
    monkeypatch.setattr(
        "packages.workflow.node_exec.get_capability_registry", lambda: reg
    )
    tenant = TenantContext(tid, uid, "user", [], False)
    scope = OrgScope(
        tenant_id=tid,
        user_id=uid,
        platform_role="user",
        primary_org_unit_id="ou-1",
        org_unit_ids=frozenset({"ou-1"}),
        subtree_paths=frozenset(),
        business_roles=frozenset({"member"}),
    )

    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="resume",
            status="published",
            ir_json={
                "nodes": [
                    {
                        "node_id": "n1",
                        "capability_id": "kb-tool",
                        "params": {},
                        "requestable": "true",
                    }
                ],
                "edges": [],
            },
            version="V1",
            revision=1,
            created_by=uid,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(wf)
        session.commit()
        started = start_run(session, tenant=tenant, org_scope=scope, workflow_id=wf.id)
        run_id = started["id"]
        wf_id = wf.id

    with patch(
        "packages.workflow.run_lifecycle.rebuild_tenant_context",
        return_value=(tenant, scope),
    ):
        await execute_run(run_id)

    with sf.Session() as session:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        assert run.status == "suspended"
        req = (
            session.query(PermissionRequest)
            .filter(PermissionRequest.run_id == run_id)
            .one()
        )
        req.status = "approved"
        issue_approval_grant(
            session,
            req=req,
            workflow_id=wf_id,
            reviewer_user_id=mgr,
            request_policy={"scope": "recurring", "default_ttl_days": 90},
        )
        session.commit()

    with (
        patch(
            "packages.workflow.run_lifecycle.rebuild_tenant_context",
            return_value=(tenant, scope),
        ),
        patch("packages.workflow.node_exec.invoke", _fake_invoke),
    ):
        await resume_run(run_id)

    with sf.Session() as session:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        assert run.status == "succeeded"
        node = (
            session.query(WorkflowRunNode)
            .filter(WorkflowRunNode.run_id == run_id)
            .one()
        )
        assert node.status == "succeeded"
        _cleanup(session, tid, run_id)


@pytest.mark.asyncio
async def test_grant_does_not_unlock_other_capability(monkeypatch):
    """批一次不等于整链：grant 只覆盖 capability_id。"""
    tid = f"e4-c-{uuid.uuid4().hex[:8]}"
    uid = f"user_{uuid.uuid4().hex[:6]}"
    sf = get_pg_session()
    reg = CapabilityRegistry()
    for cid, perm in (("kb-a", "kb:read"), ("kb-b", "kb:write")):
        reg.register(
            CapabilitySpec(
                id=cid,
                name=cid,
                kind=CapabilityKind.TOOL,
                provider=CapabilityProvider.NEXUSAI,
                spec={"governance": True, "leaf": True},
                permission=perm,
            )
        )
    monkeypatch.setattr(
        "packages.workflow.node_exec.get_capability_registry", lambda: reg
    )
    tenant = TenantContext(tid, uid, "user", [], False)
    scope = OrgScope(
        tenant_id=tid,
        user_id=uid,
        platform_role="user",
        primary_org_unit_id="ou-1",
        org_unit_ids=frozenset({"ou-1"}),
        subtree_paths=frozenset(),
        business_roles=frozenset({"member"}),
    )

    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="chain",
            status="published",
            ir_json={
                "nodes": [
                    {
                        "node_id": "n1",
                        "capability_id": "kb-a",
                        "params": {},
                        "requestable": "true",
                    },
                    {
                        "node_id": "n2",
                        "capability_id": "kb-b",
                        "params": {},
                        "requestable": "true",
                    },
                ],
                "edges": [],
            },
            version="V1",
            revision=1,
            created_by=uid,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(wf)
        session.commit()
        started = start_run(session, tenant=tenant, org_scope=scope, workflow_id=wf.id)
        run_id = started["id"]
        wf_id = wf.id

    with patch(
        "packages.workflow.run_lifecycle.rebuild_tenant_context",
        return_value=(tenant, scope),
    ):
        await execute_run(run_id)

    with sf.Session() as session:
        req = (
            session.query(PermissionRequest)
            .filter(PermissionRequest.run_id == run_id, PermissionRequest.node_id == "n1")
            .one()
        )
        req.status = "approved"
        issue_approval_grant(
            session,
            req=req,
            workflow_id=wf_id,
            reviewer_user_id="mgr",
            request_policy=None,
        )
        session.commit()

    with (
        patch(
            "packages.workflow.run_lifecycle.rebuild_tenant_context",
            return_value=(tenant, scope),
        ),
        patch("packages.workflow.node_exec.invoke", _fake_invoke),
    ):
        await resume_run(run_id)

    with sf.Session() as session:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        # n1 succeeded via grant; n2 should re-hang
        assert run.status == "suspended"
        n2 = (
            session.query(WorkflowRunNode)
            .filter(WorkflowRunNode.run_id == run_id, WorkflowRunNode.node_id == "n2")
            .one()
        )
        assert n2.status == "waiting"
        _cleanup(session, tid, run_id)
