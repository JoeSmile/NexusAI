"""Sub-agent tenant context helpers (Task 62 slice 2)."""

from __future__ import annotations

from dataclasses import replace

from packages.auth.models import TenantContext

# Sub-agents get a minimal permission set — never inherit admin / critical grants.
_SUB_AGENT_PERMISSIONS = frozenset({"chat:read", "chat:write"})


def is_sub_agent(tenant: TenantContext) -> bool:
    return (tenant.agent_role or "main").startswith("sub-agent")


def make_sub_agent_context(
    parent: TenantContext,
    *,
    agent_id: str,
    parent_trace_id: str | None = None,
) -> TenantContext:
    """Derive a restricted context for nested agent / child capability invokes."""
    role = f"sub-agent-{agent_id}"
    parent_agent = (
        agent_id
        if (parent.agent_role or "main") == "main"
        else (parent.parent_agent_id or agent_id)
    )
    return replace(
        parent,
        role="user",
        extra_permissions=[p for p in _SUB_AGENT_PERMISSIONS],
        business_roles=None,
        agent_role=role,
        parent_agent_id=parent_agent,
        parent_trace_id=parent_trace_id or parent.parent_trace_id,
        risk_level="low",
    )
