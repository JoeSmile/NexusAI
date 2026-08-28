"""Wave E3 — ancestor-chain dept_manager routing."""

from __future__ import annotations

import uuid
from datetime import datetime

from packages.workflow.notify import (
    ancestor_unit_ids,
    notify_hang_pending,
    resolve_hang_route,
)
from backend.database.pgvector_session import PermissionRequest, get_pg_session


def test_ancestor_unit_ids_nearest_first():
    assert ancestor_unit_ids("/root/div/team/") == ["team", "div", "root"]
    assert ancestor_unit_ids("a/b/") == ["b", "a"]


def test_route_prefers_ancestor_manager_over_none(monkeypatch):
    """Manager on parent unit covers child — must not escalate."""
    tid = f"e3-r-{uuid.uuid4().hex[:8]}"
    child = "ou-child"
    parent = "ou-parent"
    mgr = f"mgr_{uuid.uuid4().hex[:6]}"

    class FakeUnit:
        def __init__(self, uid: str, path: str):
            self.id = uid
            self.path = path

    units = {
        child: FakeUnit(child, f"/{parent}/{child}/"),
        parent: FakeUnit(parent, f"/{parent}/"),
    }

    class FakeMem:
        def __init__(self, user_id: str, roles: list[str]):
            self.user_id = user_id
            self.business_roles = roles

    def fake_get_unit(session, *, tenant_id, unit_id):
        return units.get(unit_id)

    def fake_list_mem(session, *, tenant_id, org_unit_id):
        if org_unit_id == parent:
            return [FakeMem(mgr, ["dept_manager"])]
        return [FakeMem("member1", ["member"])]

    monkeypatch.setattr("packages.workflow.notify.get_unit", fake_get_unit)
    monkeypatch.setattr(
        "packages.workflow.notify.list_memberships_for_unit", fake_list_mem
    )

    sf = get_pg_session()
    with sf.Session() as session:
        route = resolve_hang_route(session, tenant_id=tid, org_unit_id=child)
    assert route.escalate_to_tenant_admin is False
    assert route.matched_org_unit_id == parent
    assert mgr in route.manager_user_ids


def test_route_escalates_when_no_manager(monkeypatch):
    tid = f"e3-e-{uuid.uuid4().hex[:8]}"
    ou = "ou-alone"

    class FakeUnit:
        id = ou
        path = f"/{ou}/"

    monkeypatch.setattr(
        "packages.workflow.notify.get_unit",
        lambda session, **kw: FakeUnit(),
    )
    monkeypatch.setattr(
        "packages.workflow.notify.list_memberships_for_unit",
        lambda session, **kw: [],
    )
    sf = get_pg_session()
    with sf.Session() as session:
        route = resolve_hang_route(session, tenant_id=tid, org_unit_id=ou)
    assert route.escalate_to_tenant_admin is True
    assert route.reason == "no_dept_manager"


def test_notify_marks_escalated_when_no_manager(monkeypatch):
    tid = f"e3-n-{uuid.uuid4().hex[:8]}"
    run_id = str(uuid.uuid4())
    node_id = "n1"
    sf = get_pg_session()

    class FakeUnit:
        id = "ou-x"
        path = "/ou-x/"

    monkeypatch.setattr(
        "packages.workflow.notify.get_unit",
        lambda session, **kw: FakeUnit(),
    )
    monkeypatch.setattr(
        "packages.workflow.notify.list_memberships_for_unit",
        lambda session, **kw: [],
    )

    with sf.Session() as session:
        req = PermissionRequest(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            run_id=run_id,
            node_id=node_id,
            applicant_user_id="u1",
            needed_perm="kb:read",
            org_unit_id="ou-x",
            capability_id="kb-tool",
            status="pending",
            requestable_mode="true",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(req)
        session.commit()

    route = notify_hang_pending(run_id, node_id)
    assert route is not None
    assert route.escalate_to_tenant_admin is True

    with sf.Session() as session:
        req = (
            session.query(PermissionRequest)
            .filter(PermissionRequest.run_id == run_id)
            .one()
        )
        assert req.escalated_at is not None
        assert req.status == "pending"  # CAS 友好
        session.delete(req)
        session.commit()
