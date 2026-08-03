"""Agent 市场列表 — GET /api/agents（Task 30.24）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.core.auth.api_key_auth import verify_api_key
from backend.core.auth.models import TenantContext
from backend.core.capability.agents import agent_spec_from_capability
from backend.core.capability.models import CapabilityKind
from backend.core.capability.registry import get_capability_registry
from backend.routers.capability import _visible_to

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
@router.get("/")
async def list_agents(
    tenant: TenantContext = Depends(verify_api_key),
):
    """列出 kind=agent 的能力（按角色可见性过滤）。"""
    reg = get_capability_registry()
    specs = reg.list(kind=CapabilityKind.AGENT)
    items = []
    for s in specs:
        if not _visible_to(tenant, s):
            continue
        agent = agent_spec_from_capability(s)
        items.append(
            {
                "id": s.id,
                "name": s.name,
                "kind": s.kind.value,
                "provider": s.provider.value,
                "status": s.status.value,
                "permission": s.permission or "chat:write",
                "tenant_id": s.tenant_id,
                "role": agent.role,
                "capabilities": agent.capabilities,
                "memory": agent.memory,
            }
        )
    return {"items": items, "total": len(items)}


__all__ = ["router"]
