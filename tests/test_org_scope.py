"""Wave B2 — OrgScope facade tests."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.core.org.scope import (
    OrgScope,
    assert_org_access,
    resolve_org_scope,
    unit_visible,
    visible_org_filter,
)


def _mem(oid: str, *, primary: bool = False, roles: list[str] | None = None):
    return SimpleNamespace(
        id="m-" + oid,
        tenant_id="acme",
        user_id="u1",
        org_unit_id=oid,
        is_primary=primary,
        business_roles=roles or ["member"],
        created_at=datetime(2026, 8, 1),
    )


def test_tenant_admin_sees_full_tenant():
    scope = OrgScope(
        tenant_id="acme",
        user_id="a",
        platform_role="tenant_admin",
        primary_org_unit_id=None,
        org_unit_ids=frozenset(),
        subtree_paths=frozenset(),
        business_roles=frozenset(),
    )
    assert scope.sees_full_tenant
    assert visible_org_filter(scope)["mode"] == "tenant"
    assert_org_access(scope, "any-dept")  # no raise


def test_member_only_own_units():
    scope = OrgScope(
        tenant_id="acme",
        user_id="u",
        platform_role="user",
        primary_org_unit_id="fin",
        org_unit_ids=frozenset({"fin"}),
        subtree_paths=frozenset(),
        business_roles=frozenset({"member"}),
    )
    assert unit_visible(scope, unit_id="fin", unit_path="/fin/")
    assert not unit_visible(scope, unit_id="hr", unit_path="/hr/")
    with pytest.raises(HTTPException) as ei:
        assert_org_access(scope, "hr", unit_path="/hr/")
    assert ei.value.status_code == 403


def test_dept_manager_subtree():
    scope = OrgScope(
        tenant_id="acme",
        user_id="mgr",
        platform_role="user",
        primary_org_unit_id="fin",
        org_unit_ids=frozenset({"fin"}),
        subtree_paths=frozenset({"/fin/"}),
        business_roles=frozenset({"dept_manager"}),
    )
    assert unit_visible(scope, unit_id="acct", unit_path="/fin/acct/")
    assert not unit_visible(scope, unit_id="hr", unit_path="/hr/")
    assert_org_access(scope, "acct", unit_path="/fin/acct/")


def test_resolve_org_scope_manager_loads_paths(monkeypatch):
    session = MagicMock()
    mems = [_mem("fin", primary=True, roles=["dept_manager"])]
    monkeypatch.setattr(
        "backend.core.org.scope.list_memberships_for_user",
        lambda *a, **k: mems,
    )
    session.execute.return_value.fetchone.return_value = SimpleNamespace(
        id="fin", path="/fin/"
    )
    scope = resolve_org_scope(
        session,
        tenant_id="acme",
        user_id="mgr",
        platform_role="user",
    )
    assert scope.primary_org_unit_id == "fin"
    assert "/fin/" in scope.subtree_paths
    assert "dept_manager" in scope.business_roles
