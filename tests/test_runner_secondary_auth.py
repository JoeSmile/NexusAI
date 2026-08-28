"""Wave E2 — secondary auth: requestable fail / suspend / auto-grant."""

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
from backend.core.workflow.runner import execute_run, start_run
from backend.database.pgvector_session import (
    PermissionRequest,
    Workflow,
    WorkflowGrant,
    WorkflowRun,
    WorkflowRunNode,
    get_pg_session,
)


def _scope(tid: str, uid: str, *, roles: frozenset[str] = frozenset({"member"})) -> OrgScope:
    return OrgScope(
        tenant_id=tid,
        user_id=uid,
        platform_role="user",
        primary_org_unit_id="ou-1",
        org_unit_ids=frozenset({"ou-1"}),
        subtree_paths=frozenset({"/ou-1/"}),
        business_roles=roles,
    )


def _reg_member_cap() -> CapabilityRegistry:
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
    return reg


async def _fake_invoke(cap_id, params, tenant):
    yield {"event": "token", "data": "ok"}
    yield {"event": "done", "data": {"sources": []}}


@pytest.mark.asyncio
async def test_requestable_false_still_fails(monkeypatch):
    tid = f"e2-fail-{uuid.uuid4().hex[:8]}"
    uid = f"user_{uuid.uuid4().hex[:6]}"
    sf = get_pg_session()
    reg = _reg_member_cap()
    monkeypatch.setattr(
        "backend.core.workflow.node_exec.get_capability_registry", lambda: reg
    )
    tenant = TenantContext(tid, uid, "user", [], False)
    scope = _scope(tid, uid)

    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="nofail",
            status="published",
            ir_json={
                "nodes": [
                    {
                        "node_id": "n1",
                        "capability_id": "kb-tool",
                        "params": {},
                        "requestable": False,
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

    with patch(
        "backend.core.workflow.run_lifecycle.rebuild_tenant_context",
        return_value=(tenant, scope),
    ):
        await execute_run(run_id)

    with sf.Session() as session:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        assert run.status == "failed"
        reqs = (
            session.query(PermissionRequest)
            .filter(PermissionRequest.run_id == run_id)
            .all()
        )
        assert reqs == []
        session.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == run_id).delete()
        session.query(WorkflowRun).filter(WorkflowRun.id == run_id).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()


@pytest.mark.asyncio
async def test_requestable_true_suspends(monkeypatch):
    tid = f"e2-sus-{uuid.uuid4().hex[:8]}"
    uid = f"user_{uuid.uuid4().hex[:6]}"
    sf = get_pg_session()
    reg = _reg_member_cap()
    monkeypatch.setattr(
        "backend.core.workflow.node_exec.get_capability_registry", lambda: reg
    )
    tenant = TenantContext(tid, uid, "user", [], False)
    scope = _scope(tid, uid)

    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="hang",
            status="published",
            ir_json={
                "nodes": [
                    {
                        "node_id": "n1",
                        "capability_id": "kb-tool",
                        "params": {},
                        "requestable": True,
                        "approval_note": "need kb for report",
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

    with patch(
        "backend.core.workflow.run_lifecycle.rebuild_tenant_context",
        return_value=(tenant, scope),
    ):
        await execute_run(run_id)

    with sf.Session() as session:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        assert run.status == "suspended"
        node = (
            session.query(WorkflowRunNode)
            .filter(WorkflowRunNode.run_id == run_id)
            .one()
        )
        assert node.status == "waiting"
        req = (
            session.query(PermissionRequest)
            .filter(PermissionRequest.run_id == run_id)
            .one()
        )
        assert req.status == "pending"
        assert req.needed_perm == "kb:read"
        assert req.approval_note == "need kb for report"
        assert req.capability_id == "kb-tool"
        session.query(PermissionRequest).filter(PermissionRequest.run_id == run_id).delete()
        session.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == run_id).delete()
        session.query(WorkflowRun).filter(WorkflowRun.id == run_id).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()


@pytest.mark.asyncio
async def test_auto_grant_when_dept_manager(monkeypatch):
    tid = f"e2-ag-{uuid.uuid4().hex[:8]}"
    uid = f"mgr_{uuid.uuid4().hex[:6]}"
    sf = get_pg_session()
    reg = _reg_member_cap()
    monkeypatch.setattr(
        "backend.core.workflow.node_exec.get_capability_registry", lambda: reg
    )
    tenant = TenantContext(tid, uid, "user", [], False, business_roles=["dept_manager"])
    scope = _scope(tid, uid, roles=frozenset({"dept_manager"}))

    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="self",
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

    with (
        patch(
            "backend.core.workflow.run_lifecycle.rebuild_tenant_context",
            return_value=(tenant, scope),
        ),
        patch(
            "backend.core.workflow.node_exec.invoke",
            _fake_invoke,
        ),
    ):
        await execute_run(run_id)

    with sf.Session() as session:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        assert run.status == "succeeded"
        req = (
            session.query(PermissionRequest)
            .filter(PermissionRequest.run_id == run_id)
            .one()
        )
        assert req.status == "auto_approved"
        grant = (
            session.query(WorkflowGrant)
            .filter(WorkflowGrant.request_id == req.id)
            .one()
        )
        assert grant.origin == "auto_grant"
        assert grant.workflow_id == wf_id
        session.query(WorkflowGrant).filter(WorkflowGrant.tenant_id == tid).delete()
        session.query(PermissionRequest).filter(PermissionRequest.tenant_id == tid).delete()
        session.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == run_id).delete()
        session.query(WorkflowRun).filter(WorkflowRun.id == run_id).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()
