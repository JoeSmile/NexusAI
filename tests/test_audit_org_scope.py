"""Wave B4 — audit OrgScope filter."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.core.audit_org_scope import audit_user_filter
from packages.auth.models import TenantContext
from backend.core.org.scope import OrgScope


def test_member_only_self(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(
        "backend.core.audit_org_scope.resolve_org_scope",
        lambda *a, **k: OrgScope(
            tenant_id="acme",
            user_id="u1",
            platform_role="user",
            primary_org_unit_id="fin",
            org_unit_ids=frozenset({"fin"}),
            subtree_paths=frozenset(),
            business_roles=frozenset({"member"}),
        ),
    )
    frag, params = audit_user_filter(
        session, TenantContext("acme", "u1", "user", [], False)
    )
    assert frag == "user_id = :audit_self"
    assert params["audit_self"] == "u1"


def test_tenant_admin_no_user_filter(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(
        "backend.core.audit_org_scope.resolve_org_scope",
        lambda *a, **k: OrgScope(
            tenant_id="acme",
            user_id="a",
            platform_role="tenant_admin",
            primary_org_unit_id=None,
            org_unit_ids=frozenset(),
            subtree_paths=frozenset(),
            business_roles=frozenset(),
        ),
    )
    frag, params = audit_user_filter(
        session, TenantContext("acme", "a", "tenant_admin", [], False)
    )
    assert frag is None
    assert params == {}


def test_dept_manager_users_in_subtree(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(
        "backend.core.audit_org_scope.resolve_org_scope",
        lambda *a, **k: OrgScope(
            tenant_id="acme",
            user_id="mgr",
            platform_role="user",
            primary_org_unit_id="fin",
            org_unit_ids=frozenset({"fin"}),
            subtree_paths=frozenset({"/fin/"}),
            business_roles=frozenset({"dept_manager"}),
        ),
    )
    # path expand units, then memberships
    session.execute.return_value.fetchall.side_effect = [
        [type("R", (), {"id": "fin"})(), type("R", (), {"id": "acct"})()],
        [type("R", (), {"user_id": "u1"})(), type("R", (), {"user_id": "u2"})()],
    ]
    frag, params = audit_user_filter(
        session, TenantContext("acme", "mgr", "user", [], False)
    )
    assert frag is not None and frag.startswith("user_id IN (")
    assert set(params.values()) == {"u1", "u2"}
