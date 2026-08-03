"""Auth scope + unauthenticated surface gates (P0 security batch)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.core.auth.models import TenantContext
from backend.core.auth.scope import (
    assert_user_access,
    can_access_user,
    require_tenant_admin,
    resolve_acting_user_id,
)


def _ctx(role: str, user_id: str = "u1", tenant_id: str = "t1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        extra_permissions=[],
        is_cross_tenant=role in ("super_admin", "auditor"),
    )


def test_user_cannot_access_other_user() -> None:
    assert not can_access_user(_ctx("user"), "other")
    with pytest.raises(HTTPException) as ei:
        assert_user_access(_ctx("user"), "other")
    assert ei.value.status_code == 403
    assert ei.value.detail["code"] == "AUTH_004"


def test_user_can_access_self() -> None:
    assert assert_user_access(_ctx("user", "u1"), "u1") == "u1"


def test_tenant_admin_can_access_other() -> None:
    assert assert_user_access(_ctx("tenant_admin"), "other") == "other"


def test_require_tenant_admin() -> None:
    require_tenant_admin(_ctx("tenant_admin"))
    with pytest.raises(HTTPException) as ei:
        require_tenant_admin(_ctx("user"))
    assert ei.value.status_code == 403


def test_memory_router_exports_admin_alias() -> None:
    from backend.routers.memory import _require_memory_admin

    _require_memory_admin(_ctx("super_admin"))


def test_resolve_acting_user_id_defaults_to_self() -> None:
    assert resolve_acting_user_id(_ctx("user", "u1"), "") == "u1"
    assert resolve_acting_user_id(_ctx("user", "u1"), "u1") == "u1"


def test_resolve_acting_user_id_user_cannot_override() -> None:
    with pytest.raises(HTTPException) as ei:
        resolve_acting_user_id(_ctx("user", "u1"), "other")
    assert ei.value.status_code == 403
    assert ei.value.detail["code"] == "AUTH_004"


def test_resolve_acting_user_id_admin_may_override() -> None:
    assert resolve_acting_user_id(_ctx("tenant_admin"), "other") == "other"
    assert resolve_acting_user_id(_ctx("super_admin"), "other") == "other"


def test_resolve_acting_user_id_auditor_cannot_override() -> None:
    """auditor 跨租户只读，不可在写路径覆写 user_id（Important A）。"""
    with pytest.raises(HTTPException) as ei:
        resolve_acting_user_id(_ctx("auditor"), "other")
    assert ei.value.status_code == 403
    assert ei.value.detail["code"] == "AUTH_004"
