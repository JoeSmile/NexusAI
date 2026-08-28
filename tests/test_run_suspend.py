"""Wave E2 — suspend transaction + state machine."""

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
from backend.core.workflow.run_state import can_node_transition, can_transition
from backend.core.workflow.runner import execute_run, start_run
from backend.database.pgvector_session import (
    PermissionRequest,
    Workflow,
    WorkflowRun,
    WorkflowRunNode,
    get_pg_session,
)


def test_suspended_and_waiting_transitions():
    assert can_transition("running", "suspended")
    assert can_transition("suspended", "running")
    assert can_transition("suspended", "cancelled")
    assert can_transition("suspended", "failed")
    assert can_node_transition("running", "waiting")
    assert can_node_transition("waiting", "running")
    assert not can_transition("succeeded", "suspended")


@pytest.mark.asyncio
async def test_suspend_same_txn_fields(monkeypatch):
    tid = f"e2-txn-{uuid.uuid4().hex[:8]}"
    uid = f"user_{uuid.uuid4().hex[:6]}"
    sf = get_pg_session()
    reg = CapabilityRegistry()
    reg.register(
        CapabilitySpec(
            id="tool-x",
            name="X",
            kind=CapabilityKind.TOOL,
            provider=CapabilityProvider.NEXUSAI,
            spec={"governance": True, "leaf": True},
            permission="kb:write",
        )
    )
    monkeypatch.setattr(
        "backend.core.workflow.node_exec.get_capability_registry", lambda: reg
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
            name="txn",
            status="published",
            ir_json={
                "nodes": [
                    {
                        "node_id": "n1",
                        "capability_id": "tool-x",
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

    with patch(
        "backend.core.workflow.run_lifecycle.rebuild_tenant_context",
        return_value=(tenant, scope),
    ):
        await execute_run(run_id)

    with sf.Session() as session:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        node = (
            session.query(WorkflowRunNode)
            .filter(WorkflowRunNode.run_id == run_id)
            .one()
        )
        req = (
            session.query(PermissionRequest)
            .filter(PermissionRequest.run_id == run_id, PermissionRequest.node_id == "n1")
            .one()
        )
        assert run.status == "suspended"
        assert node.status == "waiting"
        assert req.status == "pending"
        assert req.org_unit_id == "ou-1"
        assert req.applicant_user_id == uid

        session.query(PermissionRequest).filter(PermissionRequest.run_id == run_id).delete()
        session.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == run_id).delete()
        session.query(WorkflowRun).filter(WorkflowRun.id == run_id).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()
