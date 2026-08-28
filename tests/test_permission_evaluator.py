"""Wave B2 — permission evaluator + TenantContext.has_permission delegation."""

from __future__ import annotations

from packages.auth.evaluator import evaluate_permission
from packages.auth.models import TenantContext
from packages.org.scope import OrgScope


def _scope(**kwargs) -> OrgScope:
    base = dict(
        tenant_id="acme",
        user_id="u1",
        platform_role="user",
        primary_org_unit_id="fin",
        org_unit_ids=frozenset({"fin"}),
        subtree_paths=frozenset({"/fin/"}),
        business_roles=frozenset({"dept_manager"}),
    )
    base.update(kwargs)
    return OrgScope(**base)


def test_member_no_approve():
    assert (
        evaluate_permission(
            platform_role="user",
            extra_permissions=[],
            business_roles=["member"],
            needed="workflow:approve_dept",
            org_scope=_scope(business_roles=frozenset({"member"})),
        )
        is False
    )


def test_dept_manager_approve_with_scope():
    assert (
        evaluate_permission(
            platform_role="user",
            extra_permissions=[],
            business_roles=["dept_manager"],
            needed="workflow:approve_dept",
            org_scope=_scope(),
        )
        is True
    )


def test_dept_manager_approve_without_scope_denied():
    assert (
        evaluate_permission(
            platform_role="user",
            extra_permissions=[],
            business_roles=["dept_manager"],
            needed="workflow:approve_dept",
            org_scope=None,
        )
        is False
    )


def test_unknown_business_role_ignored():
    assert (
        evaluate_permission(
            platform_role="user",
            extra_permissions=[],
            business_roles=["dept_operator", "ceo"],
            needed="workflow:approve_dept",
            org_scope=_scope(business_roles=frozenset({"dept_operator"})),
        )
        is False
    )


def test_platform_chat_still_works():
    assert (
        evaluate_permission(
            platform_role="user",
            extra_permissions=[],
            business_roles=[],
            needed="chat:write",
            org_scope=None,
        )
        is True
    )


def test_has_permission_delegates_business():
    ctx = TenantContext(
        "acme",
        "u1",
        "user",
        [],
        False,
        business_roles=["dept_manager"],
    )
    assert ctx.has_permission("chat:write") is True
    assert ctx.has_permission("workflow:approve_dept", org_scope=_scope()) is True
    assert ctx.has_permission("workflow:approve_dept") is False


def test_no_elevate_via_business_to_admin():
    ctx = TenantContext(
        "acme",
        "u1",
        "user",
        [],
        False,
        business_roles=["dept_manager"],
    )
    assert ctx.has_permission("admin:approve") is False
