"""Wave B4 — memory isolation remains user/tenant scoped (org filter N/A)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.core.auth.models import TenantContext
from backend.core.auth.scope import assert_user_access, can_access_user


def test_user_cannot_access_other_user_memory():
    t = TenantContext("acme", "alice", "user", [], False)
    assert can_access_user(t, "alice") is True
    assert can_access_user(t, "bob") is False
    with pytest.raises(HTTPException) as ei:
        assert_user_access(t, "bob")
    assert ei.value.status_code == 403


def test_tenant_admin_can_access_tenant_user():
    t = TenantContext("acme", "admin", "tenant_admin", [], False)
    assert can_access_user(t, "bob") is True


def test_cross_tenant_auditor_can_access():
    t = TenantContext("acme", "aud", "auditor", [], True)
    assert can_access_user(t, "bob") is True


def test_no_org_unit_pretend_on_memory_module():
    """Guard: memory module must not claim dept OrgScope filtering."""
    import backend.core.memory_service as ms

    assert not hasattr(ms, "list_by_org")
    assert not hasattr(ms.UnifiedMemoryService, "list_by_org")
    assert not hasattr(ms.UnifiedMemoryService, "filter_by_org_unit")
