"""E3.1 — batch approve/reject; resume only when no pending remain."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from backend.core.auth.models import TenantContext
from backend.core.org.scope import OrgScope
from backend.database.pgvector_session import (
    PermissionRequest,
    Workflow,
    WorkflowRun,
    get_pg_session,
)
from backend.routers import workflow_approvals as apr


def _scope_for(tid: str) -> OrgScope:
    return OrgScope(
        tenant_id=tid,
        user_id="admin",
        platform_role="tenant_admin",
        primary_org_unit_id="ou-1",
        org_unit_ids=frozenset({"ou-1"}),
        subtree_paths=frozenset(),
        business_roles=frozenset(),
    )


@pytest.mark.asyncio
async def test_batch_approve_resumes_only_when_clear(monkeypatch):
    tid = f"e31-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="batch",
            status="published",
            ir_json={"nodes": [], "edges": []},
            version="V1",
            revision=1,
            created_by="u1",
            request_policy={"scope": "recurring", "default_ttl_days": 30, "auto_renew": False},
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
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        reqs = [
            PermissionRequest(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                run_id=run.id,
                node_id=f"n{i}",
                applicant_user_id="u1",
                needed_perm="kb:read",
                org_unit_id="ou-1",
                capability_id="kb",
                status="pending",
                requestable_mode="true",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            for i in range(3)
        ]
        session.add_all([wf, run, *reqs])
        session.commit()
        run_id = run.id

    monkeypatch.setattr(apr, "_scope", lambda session, tenant: _scope_for(tid))
    resumed: list[str] = []
    monkeypatch.setattr(
        apr.run_svc,
        "schedule_resume",
        lambda rid: resumed.append(rid),
    )
    # issue_approval_grant needs caps — stub to avoid FK/perm complexity
    grant = MagicMock()
    grant.id = str(uuid.uuid4())
    monkeypatch.setattr(apr, "issue_approval_grant", lambda *a, **k: grant)

    tenant = TenantContext(tid, "admin", "tenant_admin", [], False)
    out = await apr.batch_review(
        apr.BatchBody(run_id=run_id, action="approve", note="ok"),
        tenant,
    )
    assert out["ok"] is True
    assert out["pending_remaining"] == 0
    assert out["resumed"] is True
    assert resumed == [run_id]
    assert sum(1 for r in out["results"] if r.get("ok")) == 3

    with sf.Session() as session:
        session.query(PermissionRequest).filter(PermissionRequest.tenant_id == tid).delete()
        session.query(WorkflowRun).filter(WorkflowRun.tenant_id == tid).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()


@pytest.mark.asyncio
async def test_batch_skips_ineligible_no_resume(monkeypatch):
    tid = f"e31s-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="batch-skip",
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
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        mine = PermissionRequest(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            run_id=run.id,
            node_id="n-mine",
            applicant_user_id="u1",
            needed_perm="kb:read",
            org_unit_id="ou-1",
            capability_id="kb",
            status="pending",
            requestable_mode="true",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        other = PermissionRequest(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            run_id=run.id,
            node_id="n-other",
            applicant_user_id="u2",
            needed_perm="kb:read",
            org_unit_id="ou-other",
            capability_id="kb",
            status="pending",
            requestable_mode="true",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add_all([wf, run, mine, other])
        session.commit()
        run_id = run.id

    # dept manager only sees ou-1
    monkeypatch.setattr(
        apr,
        "_scope",
        lambda session, tenant: OrgScope(
            tenant_id=tid,
            user_id="mgr",
            platform_role="user",
            primary_org_unit_id="ou-1",
            org_unit_ids=frozenset({"ou-1"}),
            subtree_paths=frozenset({"/ou-1"}),
            business_roles=frozenset({"dept_manager"}),
        ),
    )
    resumed: list[str] = []
    monkeypatch.setattr(apr.run_svc, "schedule_resume", lambda rid: resumed.append(rid))
    grant = MagicMock()
    grant.id = str(uuid.uuid4())
    monkeypatch.setattr(apr, "issue_approval_grant", lambda *a, **k: grant)

    tenant = TenantContext(tid, "mgr", "user", [], False)
    out = await apr.batch_review(
        apr.BatchBody(run_id=run_id, action="approve"),
        tenant,
    )
    assert out["resumed"] is False
    assert out["pending_remaining"] >= 1
    assert any(r.get("skipped") for r in out["results"])
    assert resumed == []

    with sf.Session() as session:
        session.query(PermissionRequest).filter(PermissionRequest.tenant_id == tid).delete()
        session.query(WorkflowRun).filter(WorkflowRun.tenant_id == tid).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()
