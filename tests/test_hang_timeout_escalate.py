"""Wave E3 — hang timeout escalate."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from backend.core.workflow.notify import (
    hang_escalate_after_seconds,
    maybe_escalate_timeout,
    scan_hang_timeouts,
)
from backend.database.pgvector_session import PermissionRequest, get_pg_session


def test_hang_escalate_after_env(monkeypatch):
    monkeypatch.setenv("HANG_ESCALATE_AFTER", "2h")
    assert hang_escalate_after_seconds() == 7200.0
    monkeypatch.setenv("HANG_ESCALATE_AFTER", "90")
    assert hang_escalate_after_seconds() == 90.0


def test_maybe_escalate_timeout_lazy(monkeypatch):
    monkeypatch.setenv("HANG_ESCALATE_AFTER", "3600")
    tid = f"e3-t-{uuid.uuid4().hex[:8]}"
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
            status="pending",
            requestable_mode="true",
            created_at=datetime.utcnow() - timedelta(hours=2),
            updated_at=datetime.utcnow() - timedelta(hours=2),
        )
        session.add(req)
        session.commit()
        rid = req.id

        assert maybe_escalate_timeout(session, req) is True
        session.commit()
        session.refresh(req)
        assert req.escalated_at is not None
        # idempotent
        assert maybe_escalate_timeout(session, req) is False

        session.query(PermissionRequest).filter(PermissionRequest.id == rid).delete()
        session.commit()


def test_scan_hang_timeouts(monkeypatch):
    monkeypatch.setenv("HANG_ESCALATE_AFTER", "60")
    tid = f"e3-s-{uuid.uuid4().hex[:8]}"
    sf = get_pg_session()
    with sf.Session() as session:
        old = PermissionRequest(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            run_id=str(uuid.uuid4()),
            node_id="n1",
            applicant_user_id="u1",
            needed_perm="kb:read",
            org_unit_id="ou-1",
            capability_id="kb",
            status="pending",
            requestable_mode="true",
            created_at=datetime.utcnow() - timedelta(hours=1),
            updated_at=datetime.utcnow() - timedelta(hours=1),
        )
        fresh = PermissionRequest(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            run_id=str(uuid.uuid4()),
            node_id="n2",
            applicant_user_id="u1",
            needed_perm="kb:read",
            org_unit_id="ou-1",
            capability_id="kb",
            status="pending",
            requestable_mode="true",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add_all([old, fresh])
        session.commit()
        old_id, fresh_id = old.id, fresh.id

    n = scan_hang_timeouts()
    assert n >= 1

    with sf.Session() as session:
        o = session.query(PermissionRequest).filter(PermissionRequest.id == old_id).one()
        f = session.query(PermissionRequest).filter(PermissionRequest.id == fresh_id).one()
        assert o.escalated_at is not None
        assert f.escalated_at is None
        session.query(PermissionRequest).filter(PermissionRequest.tenant_id == tid).delete()
        session.commit()
