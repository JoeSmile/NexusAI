"""Wave E1 — S1–S5 security gates."""

from __future__ import annotations

import pytest

from backend.core.auth.models import TenantContext
from backend.core.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
)
from backend.core.org.scope import OrgScope
from backend.core.workflow.security_gates import (
    HangGateError,
    assert_hang_wait_allowed,
    assert_no_browser_delegation,
    effective_requestable,
    infer_sensitive_capability,
    normalize_requestable,
    resolve_acting_user,
)


def _tenant(**kwargs) -> TenantContext:
    base = dict(
        tenant_id="t1",
        user_id="u1",
        role="user",
        extra_permissions=[],
        is_cross_tenant=False,
        acting_user_id="u1",
    )
    base.update(kwargs)
    return TenantContext(**base)  # type: ignore[arg-type]


def _scope(**kwargs) -> OrgScope:
    base = dict(
        tenant_id="t1",
        user_id="u1",
        platform_role="user",
        primary_org_unit_id="ou-1",
        org_unit_ids=frozenset({"ou-1"}),
        subtree_paths=frozenset(),
        business_roles=frozenset({"member"}),
    )
    base.update(kwargs)
    return OrgScope(**base)  # type: ignore[arg-type]


def _cap(**kwargs) -> CapabilitySpec:
    base = dict(
        id="tool-x",
        name="X",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        spec={"governance": True},
        permission="chat:write",
        tenant_id="*",
    )
    base.update(kwargs)
    return CapabilitySpec(**base)  # type: ignore[arg-type]


def test_s1_rejects_body_acting_user_override():
    t = _tenant()
    with pytest.raises(HangGateError) as ei:
        resolve_acting_user(t, body_acting_user_id="other")
    assert ei.value.code == "S1_ACTING_USER_OVERRIDE"


def test_s1_allows_matching_body_or_none():
    t = _tenant()
    assert resolve_acting_user(t, body_acting_user_id=None) == "u1"
    assert resolve_acting_user(t, body_acting_user_id="u1") == "u1"


def test_s2_normalize_and_false_blocks_hang():
    assert normalize_requestable(True) == "true"
    assert normalize_requestable(False) == "false"
    assert normalize_requestable(None) == "true"
    with pytest.raises(HangGateError) as ei:
        assert_hang_wait_allowed(
            tenant=_tenant(),
            org_scope=_scope(),
            node_requestable=False,
            capability=_cap(),
        )
    assert ei.value.code == "S2_NOT_REQUESTABLE"


def test_s2_infer_sensitive_from_tenant_and_perm():
    assert infer_sensitive_capability(
        _cap(tenant_id="other"), acting_tenant_id="t1"
    )
    assert infer_sensitive_capability(
        _cap(permission="admin:llm_key"), acting_tenant_id="t1"
    )
    assert not infer_sensitive_capability(
        _cap(permission="chat:write", tenant_id="*"), acting_tenant_id="t1"
    )
    # 节点 true + 敏感能力 → 升格 sensitive
    assert (
        effective_requestable("true", _cap(permission="admin:*"), acting_tenant_id="t1")
        == "sensitive"
    )


def test_s3_s5_require_realtime_org_scope():
    with pytest.raises(HangGateError) as ei:
        assert_hang_wait_allowed(
            tenant=_tenant(),
            org_scope=None,
            node_requestable="true",
            capability=_cap(),
        )
    assert ei.value.code == "S5_NO_ORG_SCOPE"


def test_s4_rejects_browser_delegation():
    with pytest.raises(HangGateError) as ei:
        assert_no_browser_delegation({"delegation_id": "g1"})
    assert ei.value.code == "S4_BROWSER_DELEGATION"


def test_hang_allowed_for_requestable_true():
    r = assert_hang_wait_allowed(
        tenant=_tenant(),
        org_scope=_scope(),
        node_requestable="true",
        capability=_cap(),
    )
    assert r.allowed and r.requestable == "true"
