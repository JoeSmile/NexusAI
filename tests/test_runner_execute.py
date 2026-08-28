"""Wave D3 — runner execute happy path with mocked invoke."""

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
from backend.database.pgvector_session import Workflow, WorkflowRun, WorkflowRunNode, get_pg_session


async def _fake_invoke(cap_id, payload, tenant):
    yield {"event": "token", "data": "hello evidence answer"}
    yield {
        "event": "done",
        "data": {
            "capability_id": cap_id,
            "executor": "rag",
            "sources": [{"content": "cite me", "metadata": {"title": "doc1"}}],
        },
    }


@pytest.mark.asyncio
async def test_execute_run_succeeds_with_evidence(monkeypatch):
    tid = f"run-ex-{uuid.uuid4().hex[:8]}"
    uid = f"admin_{uuid.uuid4().hex[:6]}"
    sf = get_pg_session()

    reg = CapabilityRegistry()
    reg.register(
        CapabilitySpec(
            id="rag-ask",
            name="RAG",
            kind=CapabilityKind.TOOL,
            provider=CapabilityProvider.NEXUSAI,
            spec={"governance": True, "leaf": True, "executor": "rag"},
            permission="chat:write",
            param_spec={"query": {"type": "string", "required": True}},
        )
    )
    monkeypatch.setattr(
        "backend.core.workflow.node_exec.get_capability_registry", lambda: reg
    )

    tenant = TenantContext(tid, uid, "tenant_admin", ["chat:write"], False)
    scope = OrgScope(
        tenant_id=tid,
        user_id=uid,
        platform_role="tenant_admin",
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
            name="ex",
            status="published",
            ir_json={
                "ir_schema": "1",
                "nodes": [
                    {
                        "node_id": "n1",
                        "capability_id": "rag-ask",
                        "params": {"query": "q"},
                    }
                ],
                "edges": [],
            },
            version="V1.0.0",
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

    with patch("backend.core.workflow.node_exec.invoke", _fake_invoke):
        with patch(
            "backend.core.workflow.run_lifecycle.rebuild_tenant_context",
            return_value=(tenant, scope),
        ):
            await execute_run(run_id)

    with sf.Session() as session:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        assert run.status == "succeeded"
        nodes = (
            session.query(WorkflowRunNode)
            .filter(WorkflowRunNode.run_id == run_id)
            .all()
        )
        assert len(nodes) == 1
        assert nodes[0].status == "succeeded"
        ev = (nodes[0].output_json or {}).get("evidence") or []
        assert len(ev) >= 1

        session.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == run_id).delete()
        session.query(WorkflowRun).filter(WorkflowRun.id == run_id).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()
