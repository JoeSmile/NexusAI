"""Wave E — cancel linkage + grant TTL expire → re-request."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from packages.auth.models import TenantContext
from packages.org.scope import OrgScope
from packages.workflow.grants import (
    cap_entry,
    expire_stale_approvals_for_node,
)
from packages.workflow.runner import cancel_run
from packages.database.pgvector_session import (
    PermissionRequest,
    Workflow,
    WorkflowGrant,
    WorkflowRun,
    get_pg_session,
)


def test_cancel_suspended_marks_request_cancelled():
    tid = f"e-cx-{uuid.uuid4().hex[:8]}"
    uid = f"u_{uuid.uuid4().hex[:6]}"
    sf = get_pg_session()
    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="cx",
            status="published",
            ir_json={"nodes": [], "edges": []},
            version="V1",
            revision=1,
            created_by=uid,
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
            acting_user_id=uid,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        req = PermissionRequest(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            run_id=run.id,
            node_id="n1",
            applicant_user_id=uid,
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
        run_id, req_id = run.id, req.id

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
        out = cancel_run(session, tenant=tenant, org_scope=scope, run_id=run_id)
        assert out["status"] == "cancelled"
        assert out["requests_cancelled"] == 1
        req2 = session.query(PermissionRequest).filter(PermissionRequest.id == req_id).one()
        assert req2.status == "cancelled"

        session.query(PermissionRequest).filter(PermissionRequest.tenant_id == tid).delete()
        session.query(WorkflowRun).filter(WorkflowRun.tenant_id == tid).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()


def test_expire_stale_grant_marks_request_expired():
    tid = f"e-ex-{uuid.uuid4().hex[:8]}"
    uid = "u1"
    sf = get_pg_session()
    with sf.Session() as session:
        req = PermissionRequest(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            run_id=str(uuid.uuid4()),
            node_id="n1",
            applicant_user_id=uid,
            needed_perm="kb:read",
            org_unit_id="ou-1",
            capability_id="kb-tool",
            status="approved",
            requestable_mode="true",
            created_at=datetime.utcnow() - timedelta(days=100),
            updated_at=datetime.utcnow() - timedelta(days=100),
            reviewed_at=datetime.utcnow() - timedelta(days=100),
        )
        grant = WorkflowGrant(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            request_id=req.id,
            workflow_id=str(uuid.uuid4()),
            scope="recurring",
            applicant_user_id=uid,
            caps=[cap_entry(capability_id="kb-tool", permission="kb:read")],
            issued_at=datetime.utcnow() - timedelta(days=100),
            expires_at=datetime.utcnow() - timedelta(days=1),
            origin="approval",
        )
        session.add_all([req, grant])
        session.commit()
        wf_id, run_id, req_id = grant.workflow_id, req.run_id, req.id

        n = expire_stale_approvals_for_node(
            session,
            tenant_id=tid,
            workflow_id=wf_id,
            run_id=run_id,
            node_id="n1",
            applicant_user_id=uid,
            capability_id="kb-tool",
        )
        session.commit()
        assert n == 1
        req2 = session.query(PermissionRequest).filter(PermissionRequest.id == req_id).one()
        assert req2.status == "expired"
        assert "grant_ttl_expired" in (req2.review_reason or "")

        session.query(WorkflowGrant).filter(WorkflowGrant.tenant_id == tid).delete()
        session.query(PermissionRequest).filter(PermissionRequest.tenant_id == tid).delete()
        session.commit()
