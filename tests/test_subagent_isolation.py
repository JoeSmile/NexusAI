"""Task 62 slice 2 — sub-agent permission isolation."""

from __future__ import annotations

import pytest

from packages.auth.models import TenantContext
from packages.auth.subagent import is_sub_agent, make_sub_agent_context
from backend.core.capability.governance_chain import run_governance_chain
from backend.core.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
)
from backend.core.errors import ErrorCode, NexusAIException


@pytest.fixture
def admin_tenant() -> TenantContext:
    return TenantContext(
        "t1",
        "u1",
        "tenant_admin",
        ["admin:*", "chat:write"],
        False,
    )


def test_make_sub_agent_restricts_permissions(admin_tenant: TenantContext) -> None:
    sub = make_sub_agent_context(
        admin_tenant, agent_id="child-agent", parent_trace_id="ptrace"
    )
    assert sub.agent_role == "sub-agent-child-agent"
    assert sub.parent_agent_id == "child-agent"
    assert sub.parent_trace_id == "ptrace"
    assert sub.risk_level == "low"
    assert is_sub_agent(sub)
    assert not sub.has_permission("admin:llm_key")
    assert sub.has_permission("chat:write")


def test_governance_blocks_sub_agent_critical(admin_tenant: TenantContext) -> None:
    sub = make_sub_agent_context(admin_tenant, agent_id="a1")
    critical = CapabilitySpec(
        id="danger.delete",
        name="delete",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        permission="admin:*",
        spec={"risk_level": "critical"},
    )

    def allow(_spec, _tenant):
        return None

    with pytest.raises(NexusAIException) as ei:
        run_governance_chain(critical, sub, {}, check_permission=allow)
    assert ei.value.code == ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS.value


def test_governance_blocks_sub_agent_high(admin_tenant: TenantContext) -> None:
    sub = make_sub_agent_context(admin_tenant, agent_id="a1")
    high_risk = CapabilitySpec(
        id="tool.external",
        name="external",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        permission="chat:write",
        spec={"risk_level": "high"},
    )

    def allow(_spec, _tenant):
        return None

    with pytest.raises(NexusAIException) as ei:
        run_governance_chain(high_risk, sub, {}, check_permission=allow)
    assert ei.value.code == ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS.value


def test_governance_allows_sub_agent_low_risk(admin_tenant: TenantContext) -> None:
    sub = make_sub_agent_context(admin_tenant, agent_id="a1")
    safe = CapabilitySpec(
        id="tool.safe",
        name="safe",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        permission="chat:write",
        spec={"risk_level": "low"},
    )

    def allow(_spec, _tenant):
        return None

    explain = run_governance_chain(safe, sub, {}, check_permission=allow)
    assert explain.allowed is True
