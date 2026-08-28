"""Wave E5 — hang-wait audit trail fields."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
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
from backend.core.workflow.notify import mark_escalated
from backend.core.workflow.runner import execute_run, start_run
from backend.database.pgvector_session import (
    PermissionRequest,
    Workflow,
    WorkflowRun,
    WorkflowRunNode,
    get_pg_session,
)
from backend.routers import workflow_approvals as apr


@pytest.mark.asyncio
async def test_suspend_and_escalate_audit_fields(monkeypatch):
    records: list[dict] = []

    def _cap(rec):
        records.append(dict(rec))

    tid = f"e5-{uuid.uuid4().hex[:8]}"
    uid = f"user_{uuid.uuid4().hex[:6]}"
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
        "backend.core.workflow.node_exec.get_capability_registry", lambda: reg
    )
    tenant = TenantContext(tid, uid, "user", [], False, credential_kind="human_session")
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
            name="aud",
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

    with (
        patch(
            "backend.core.workflow.run_lifecycle.rebuild_tenant_context",
            return_value=(tenant, scope),
        ),
        patch("backend.core.workflow.runner_shared.write_audit_sync", _cap),
        patch("backend.core.workflow.notify.write_audit_sync", _cap),
        patch("backend.core.workflow.notify.get_unit", return_value=None),
    ):
        await execute_run(run_id)

    sus = [r for r in records if r.get("action") == "workflow.run.suspended"]
    assert sus, records
    assert sus[0]["run_id"] == run_id
    assert sus[0]["node_id"] == "n1"
    assert sus[0]["user_id"] == uid
    assert sus[0].get("credential_kind") == "human_session"

    esc = [
        r
        for r in records
        if str(r.get("action") or "").endswith("escalate_no_dept_manager")
    ]
    assert esc, records
    assert esc[0]["run_id"] == run_id
    assert esc[0]["node_id"] == "n1"

    with sf.Session() as session:
        session.query(PermissionRequest).filter(PermissionRequest.run_id == run_id).delete()
        session.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == run_id).delete()
        session.query(WorkflowRun).filter(WorkflowRun.id == run_id).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()


def test_timeout_escalate_audit(monkeypatch):
    records: list[dict] = []
    monkeypatch.setattr(
        "backend.core.workflow.notify.write_audit_sync",
        lambda rec: records.append(dict(rec)),
    )
    tid = f"e5-t-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    with sf.Session() as session:
        req = PermissionRequest(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            run_id=str(uuid.uuid4()),
            node_id="n9",
            applicant_user_id="u1",
            needed_perm="kb:read",
            org_unit_id="ou-1",
            capability_id="kb",
            status="pending",
            requestable_mode="true",
            created_at=datetime.utcnow() - timedelta(days=2),
            updated_at=datetime.utcnow() - timedelta(days=2),
        )
        session.add(req)
        session.commit()
        assert mark_escalated(session, req, reason="escalate_timeout") is True
        session.commit()
        rid = req.id

    assert any(
        r.get("action") == "workflow.hang.escalate_timeout"
        and r.get("node_id") == "n9"
        and r.get("user_id") == "u1"
        for r in records
    )
    with sf.Session() as session:
        session.query(PermissionRequest).filter(PermissionRequest.id == rid).delete()
        session.commit()


@pytest.mark.asyncio
async def test_approve_audit_credential_kind_delegation(monkeypatch):
    records: list[dict] = []
    tid = f"e5-a-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    with sf.Session() as session:
        from backend.database.pgvector_session import Workflow, WorkflowRun

        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="a",
            status="published",
            ir_json={"nodes": [], "edges": []},
            version="V1",
            revision=1,
            created_by="u1",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            workflow_id=wf.id,
            org_unit_id="ou-1",
            status="suspended",
            ir_snapshot={"nodes": [], "edges": []},
            workflow_version="V1",
            workflow_revision=1,
            acting_user_id="u1",
            credential_kind="human_session",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        req = PermissionRequest(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            run_id=run.id,
            node_id="n1",
            applicant_user_id="u1",
            needed_perm="kb:read",
            org_unit_id="ou-1",
            capability_id="kb",
            status="pending",
            requestable_mode="true",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add_all([wf, run, req])
        session.commit()
        req_id = req.id
        run_id = run.id

    monkeypatch.setattr(apr, "write_audit_sync", lambda rec: records.append(dict(rec)))
    monkeypatch.setattr(
        apr,
        "_scope",
        lambda session, tenant: OrgScope(
            tenant_id=tid,
            user_id="admin",
            platform_role="tenant_admin",
            primary_org_unit_id="ou-1",
            org_unit_ids=frozenset({"ou-1"}),
            subtree_paths=frozenset(),
            business_roles=frozenset(),
        ),
    )
    monkeypatch.setattr(apr.run_svc, "schedule_resume", lambda rid: None)

    tenant = TenantContext(tid, "admin", "tenant_admin", [], False)
    out = await apr.approve(req_id, None, tenant)
    assert out["ok"] is True
    ap = [r for r in records if r.get("action") == "workflow.approve"]
    assert ap
    assert ap[0]["credential_kind"] == "delegation"
    assert ap[0]["run_id"] == run_id
    assert ap[0]["node_id"] == "n1"
    assert ap[0]["user_id"] == "admin"

    with sf.Session() as session:
        from backend.database.pgvector_session import WorkflowGrant

        session.query(WorkflowGrant).filter(WorkflowGrant.tenant_id == tid).delete()
        session.query(PermissionRequest).filter(PermissionRequest.tenant_id == tid).delete()
        session.query(WorkflowRun).filter(WorkflowRun.tenant_id == tid).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()
