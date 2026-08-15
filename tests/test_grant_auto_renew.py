"""E3.2 — auto_renew + cron parse."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from backend.core.workflow.grants import normalize_request_policy, renew_grant
from backend.core.workflow.scheduler import parse_cron_next
from backend.database.pgvector_session import (
    PermissionRequest,
    Workflow,
    WorkflowGrant,
    get_pg_session,
)


def test_parse_cron_daily_8am():
    after = datetime(2026, 8, 15, 9, 0, 0)
    nxt = parse_cron_next("0 8 * * *", after=after)
    assert nxt.hour == 8 and nxt.minute == 0
    assert nxt.date() == datetime(2026, 8, 16).date()


def test_renew_grant_idempotent():
    tid = f"e32-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="renew",
            status="published",
            ir_json={"nodes": [], "edges": []},
            version="V1",
            revision=1,
            created_by="u1",
            request_policy={
                "scope": "recurring",
                "default_ttl_days": 30,
                "auto_renew": True,
            },
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
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
        grant = WorkflowGrant(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            request_id=req.id,
            workflow_id=wf.id,
            scope="recurring",
            applicant_user_id="u1",
            caps=[{"capability_id": "kb", "permission": "kb:read"}],
            issued_at=datetime.utcnow() - timedelta(days=20),
            expires_at=datetime.utcnow() + timedelta(days=2),
            revoked_at=None,
            origin="approval",
        )
        session.add_all([wf, req, grant])
        session.commit()
        gid = grant.id
        policy = normalize_request_policy(wf.request_policy)

        g1 = renew_grant(session, grant=grant, request_policy=policy)
        session.commit()
        assert g1 is not None
        assert g1.origin == f"renew:{gid}"
        assert g1.expires_at > datetime.utcnow() + timedelta(days=20)

        g2 = renew_grant(session, grant=grant, request_policy=policy)
        session.commit()
        assert g2 is not None
        assert g2.id == g1.id  # 幂等

        session.query(WorkflowGrant).filter(WorkflowGrant.tenant_id == tid).delete()
        session.query(PermissionRequest).filter(PermissionRequest.tenant_id == tid).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()


def test_renew_skips_when_auto_renew_false():
    tid = f"e32f-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    with sf.Session() as session:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            org_unit_id="ou-1",
            name="no-renew",
            status="published",
            ir_json={"nodes": [], "edges": []},
            version="V1",
            revision=1,
            created_by="u1",
            request_policy={"auto_renew": False, "default_ttl_days": 7},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
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
        grant = WorkflowGrant(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            request_id=req.id,
            workflow_id=wf.id,
            scope="recurring",
            applicant_user_id="u1",
            caps=[{"capability_id": "kb", "permission": "kb:read"}],
            issued_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=1),
            origin="approval",
        )
        session.add_all([wf, req, grant])
        session.commit()
        out = renew_grant(
            session,
            grant=grant,
            request_policy=normalize_request_policy(wf.request_policy),
        )
        assert out is None
        session.query(WorkflowGrant).filter(WorkflowGrant.tenant_id == tid).delete()
        session.query(PermissionRequest).filter(PermissionRequest.tenant_id == tid).delete()
        session.query(Workflow).filter(Workflow.tenant_id == tid).delete()
        session.commit()
