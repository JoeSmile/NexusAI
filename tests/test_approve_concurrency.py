"""Wave E4 — approve CAS concurrency + org deny."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from backend.core.auth.models import TenantContext
from backend.core.org.scope import OrgScope
from backend.core.workflow.grants import can_review_request
from backend.database.pgvector_session import PermissionRequest, get_pg_session
from backend.routers import workflow_approvals as apr


@pytest.mark.asyncio
async def test_double_approve_second_409(monkeypatch):
    tid = f"e4-d-{uuid.uuid4().hex[:8]}"
    rid = str(uuid.uuid4())
    sf = get_pg_session()
    with sf.Session() as session:
        req = PermissionRequest(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            run_id=rid,
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
        session.add(req)
        session.commit()
        req_id = req.id

        # first CAS
        r1 = session.execute(
            text(
                "UPDATE permission_requests SET status='approved', updated_at=:now "
                "WHERE id=:id AND status='pending'"
            ),
            {"id": req_id, "now": datetime.utcnow()},
        )
        assert r1.rowcount == 1
        session.commit()

        # second CAS
        r2 = session.execute(
            text(
                "UPDATE permission_requests SET status='approved', updated_at=:now "
                "WHERE id=:id AND status='pending'"
            ),
            {"id": req_id, "now": datetime.utcnow()},
        )
        assert r2.rowcount == 0
        session.query(PermissionRequest).filter(PermissionRequest.id == req_id).delete()
        session.commit()


def test_other_dept_manager_cannot_review():
    tid = f"e4-o-{uuid.uuid4().hex[:8]}"
    req = PermissionRequest(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        run_id=str(uuid.uuid4()),
        node_id="n1",
        applicant_user_id="u1",
        needed_perm="kb:read",
        org_unit_id="ou-other",
        capability_id="kb",
        status="pending",
        requestable_mode="true",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    tenant = TenantContext(tid, "mgr", "user", [], False, business_roles=["dept_manager"])
    scope = OrgScope(
        tenant_id=tid,
        user_id="mgr",
        platform_role="user",
        primary_org_unit_id="ou-mine",
        org_unit_ids=frozenset({"ou-mine"}),
        subtree_paths=frozenset({"/ou-mine/"}),
        business_roles=frozenset({"dept_manager"}),
    )
    assert can_review_request(tenant, scope, req=req, session=None) is False


def test_tenant_admin_can_review_sensitive():
    tid = f"e4-s-{uuid.uuid4().hex[:8]}"
    req = PermissionRequest(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        run_id=str(uuid.uuid4()),
        node_id="n1",
        applicant_user_id="u1",
        needed_perm="admin:llm_key",
        org_unit_id="ou-1",
        capability_id="secret",
        status="pending",
        requestable_mode="sensitive",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    admin = TenantContext(tid, "admin", "tenant_admin", [], False)
    scope = OrgScope(
        tenant_id=tid,
        user_id="admin",
        platform_role="tenant_admin",
        primary_org_unit_id="ou-1",
        org_unit_ids=frozenset({"ou-1"}),
        subtree_paths=frozenset(),
        business_roles=frozenset(),
    )
    assert can_review_request(admin, scope, req=req, session=None) is True

    mgr = TenantContext(tid, "mgr", "user", [], False, business_roles=["dept_manager"])
    mgr_scope = OrgScope(
        tenant_id=tid,
        user_id="mgr",
        platform_role="user",
        primary_org_unit_id="ou-1",
        org_unit_ids=frozenset({"ou-1"}),
        subtree_paths=frozenset({"/ou-1/"}),
        business_roles=frozenset({"dept_manager"}),
    )
    assert can_review_request(mgr, mgr_scope, req=req, session=None) is False


@pytest.mark.asyncio
async def test_approve_endpoint_409_when_already_done(monkeypatch):
    tid = f"e4-a-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    with sf.Session() as session:
        req = PermissionRequest(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            run_id=str(uuid.uuid4()),
            node_id="n1",
            applicant_user_id="u1",
            needed_perm="kb:read",
            org_unit_id="ou-1",
            capability_id="kb",
            status="approved",
            requestable_mode="true",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(req)
        session.commit()
        req_id = req.id

    monkeypatch.setattr(apr, "_scope", lambda session, tenant: OrgScope(
        tenant_id=tid,
        user_id="admin",
        platform_role="tenant_admin",
        primary_org_unit_id="ou-1",
        org_unit_ids=frozenset({"ou-1"}),
        subtree_paths=frozenset(),
        business_roles=frozenset(),
    ))

    tenant = TenantContext(tid, "admin", "tenant_admin", [], False)
    with pytest.raises(HTTPException) as ei:
        await apr.approve(req_id, None, tenant)
    assert ei.value.status_code == 409

    with sf.Session() as session:
        session.query(PermissionRequest).filter(PermissionRequest.id == req_id).delete()
        session.commit()


@pytest.mark.asyncio
async def test_reject_fails_run(monkeypatch):
    tid = f"e4-rj-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    from backend.database.pgvector_session import Workflow, WorkflowRun

    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="rj",
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
        req_id, run_id = req.id, run.id

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
    tenant = TenantContext(tid, "admin", "tenant_admin", [], False)
    out = await apr.reject(req_id, apr.RejectBody(reason="nope"), tenant)
    assert out["status"] == "rejected"

    with sf.Session() as session:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        req = session.query(PermissionRequest).filter(PermissionRequest.id == req_id).one()
        assert run.status == "failed"
        assert "permission_rejected" in (run.error_message or "")
        assert req.status == "rejected"
        session.query(PermissionRequest).filter(PermissionRequest.tenant_id == tid).delete()
        session.query(WorkflowRun).filter(WorkflowRun.tenant_id == tid).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()
