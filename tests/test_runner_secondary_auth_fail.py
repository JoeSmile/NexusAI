"""Wave D3 — secondary auth fail-closed."""

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
from packages.org.scope import OrgScope
from packages.workflow.runner import execute_run, start_run
from backend.database.pgvector_session import Workflow, WorkflowRun, WorkflowRunNode, get_pg_session


@pytest.mark.asyncio
async def test_secondary_auth_fail_marks_run_failed(monkeypatch):
    tid = f"run-auth-{uuid.uuid4().hex[:8]}"
    uid = f"user_{uuid.uuid4().hex[:6]}"
    sf = get_pg_session()

    reg = CapabilityRegistry()
    reg.register(
        CapabilitySpec(
            id="admin-tool",
            name="Admin",
            kind=CapabilityKind.TOOL,
            provider=CapabilityProvider.NEXUSAI,
            spec={"governance": True, "leaf": True},
            permission="admin:*",
        )
    )
    monkeypatch.setattr(
        "packages.workflow.node_exec.get_capability_registry", lambda: reg
    )

    # user without admin:*
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
            name="authfail",
            status="published",
            ir_json={
                "nodes": [
                    {
                        "node_id": "n1",
                        "capability_id": "admin-tool",
                        "params": {},
                        "requestable": False,  # Wave E: explicit fail-closed
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
        started = start_run(
            session, tenant=tenant, org_scope=scope, workflow_id=wf.id
        )
        run_id = started["id"]

    with patch(
        "packages.workflow.run_lifecycle.rebuild_tenant_context",
        return_value=(tenant, scope),
    ):
        await execute_run(run_id)

    with sf.Session() as session:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        assert run.status == "failed"
        assert run.error_code in ("AUTH_002", "HTTP") or (
            run.error_message and "auth" in (run.error_message or "").lower()
        ) or run.error_code == "AUTH_002"
        # detail from HTTPException uses AUTH_002
        nodes = (
            session.query(WorkflowRunNode)
            .filter(WorkflowRunNode.run_id == run_id)
            .all()
        )
        assert nodes and nodes[0].status == "failed"

        session.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == run_id).delete()
        session.query(WorkflowRun).filter(WorkflowRun.id == run_id).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()
