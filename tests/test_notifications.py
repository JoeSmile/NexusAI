"""Task 44 — notifications table + ChannelProvider + inbox."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from backend.database.pgvector_session import Notification, get_pg_session
from backend.modules.notification import channels as ch
from backend.modules.notification.service import (
    list_inbox,
    mark_read,
    notify,
    unread_count,
)


@pytest.fixture(autouse=True)
def _reset_providers():
    ch.clear_providers()
    ch.ensure_default_providers()
    yield
    ch.clear_providers()


@pytest.fixture()
def ensure_table():
    sf = get_pg_session()
    Notification.__table__.create(sf.engine, checkfirst=True)
    yield sf


def test_inbox_channel_write_and_isolation(ensure_table):
    tid = f"n44-{uuid.uuid4().hex[:8]}"
    u_a = f"ua_{uuid.uuid4().hex[:6]}"
    u_b = f"ub_{uuid.uuid4().hex[:6]}"
    payload = {"run_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4())}

    sent = notify(tid, u_a, "hang.pending", payload)
    assert "inbox" in sent
    # sensitive keys stripped
    rows = list_inbox(tenant_id=tid, user_id=u_a)
    assert len(rows) == 1
    assert rows[0].payload.get("run_id") == payload["run_id"]
    assert "secret" not in rows[0].payload

    notify(tid, u_a, "hang.pending", {**payload, "secret": "x"})
    rows = list_inbox(tenant_id=tid, user_id=u_a)
    assert all("secret" not in (r.payload or {}) for r in rows)

    notify(tid, u_b, "hang.approved", payload)
    a_rows = list_inbox(tenant_id=tid, user_id=u_a)
    b_rows = list_inbox(tenant_id=tid, user_id=u_b)
    assert all(r.user_id == u_a for r in a_rows)
    assert all(r.user_id == u_b for r in b_rows)
    assert unread_count(tenant_id=tid, user_id=u_a) >= 1
    assert unread_count(tenant_id=tid, user_id=u_b) == 1

    nid = a_rows[0].id
    assert mark_read(tenant_id=tid, user_id=u_a, notification_id=nid) is True
    assert mark_read(tenant_id=tid, user_id=u_b, notification_id=nid) is False

    # cleanup
    sf = ensure_table
    with sf.Session() as session:
        session.query(Notification).filter(Notification.tenant_id == tid).delete()
        session.commit()


def test_unavailable_provider_skipped(ensure_table, monkeypatch):
    tid = f"n44s-{uuid.uuid4().hex[:8]}"
    uid = f"u_{uuid.uuid4().hex[:6]}"

    class Boom:
        name = "boom"

        def available(self):
            return True

        def send(self, session, **kwargs):
            raise RuntimeError("boom")

    ch.register_provider(Boom())
    # fail soft — still returns inbox if boom fails independently
    sent = notify(tid, uid, "hang.pending", {"run_id": "r1"})
    assert "inbox" in sent
    assert "boom" not in sent

    stub = ch.WecomChannel()
    assert stub.available() is False
    ch.register_provider(stub)
    avail = [p.name for p in ch.list_available_providers()]
    assert "wecom" not in avail
    assert "inbox" in avail

    sf = ensure_table
    with sf.Session() as session:
        session.query(Notification).filter(Notification.tenant_id == tid).delete()
        session.commit()


def test_refs_only_strips_reason():
    from backend.modules.notification.service import refs_only

    clean = refs_only(
        {
            "run_id": "r1",
            "request_id": "q1",
            "reason": "should_not_store",
            "secret": "x",
        }
    )
    assert clean == {"run_id": "r1", "request_id": "q1"}
    assert "reason" not in clean


def test_notify_failure_does_not_raise(ensure_table, monkeypatch):
    """Channel 全挂也不抛。"""

    def boom_providers():
        class Dead:
            name = "dead"

            def available(self):
                return True

            def send(self, *a, **k):
                raise RuntimeError("dead")

        return [Dead()]

    monkeypatch.setattr(
        "backend.modules.notification.service.list_available_providers",
        boom_providers,
    )
    out = notify("t", "u", "hang.pending", {"run_id": "x"})
    assert out == []


def test_hang_pending_wires_inbox(ensure_table, monkeypatch):
    """notify_hang_pending → hang.pending inbox（有经理时）。"""
    from backend.core.workflow.notify import HangRoute, notify_hang_pending
    from backend.database.pgvector_session import PermissionRequest

    tid = f"n44h-{uuid.uuid4().hex[:8]}"
    run_id = str(uuid.uuid4())
    node_id = "n1"
    mgr = f"mgr_{uuid.uuid4().hex[:6]}"
    sf = ensure_table

    monkeypatch.setattr(
        "backend.core.workflow.notify.resolve_hang_route",
        lambda session, **kw: HangRoute(
            manager_user_ids=(mgr,),
            matched_org_unit_id="ou1",
            escalate_to_tenant_admin=False,
            reason="dept_manager",
        ),
    )

    with sf.Session() as session:
        session.add(
            PermissionRequest(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                run_id=run_id,
                node_id=node_id,
                applicant_user_id="u1",
                needed_perm="kb:read",
                org_unit_id="ou1",
                capability_id="kb-tool",
                status="pending",
                requestable_mode="true",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        session.commit()

    route = notify_hang_pending(run_id, node_id)
    assert route is not None
    rows = list_inbox(tenant_id=tid, user_id=mgr)
    assert any(r.type == "hang.pending" for r in rows)

    with sf.Session() as session:
        session.query(Notification).filter(Notification.tenant_id == tid).delete()
        session.query(PermissionRequest).filter(
            PermissionRequest.run_id == run_id
        ).delete()
        session.commit()
