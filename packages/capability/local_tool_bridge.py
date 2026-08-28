"""Bridge notes: legacy ToolCaller → CapabilityRegistry (Task 66 slice 0).

Production tool execution path:
  CapabilitySpec(kind=TOOL) → registry.register → tool_search upsert
  → invoke() governance chain → handler

Legacy path (this package):
  packages.agent_runtime.tool_caller.ToolRegistry — agent /agent/* only; converge in slice 1.
"""

from __future__ import annotations

from typing import Any

from packages.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
)


def legacy_tool_to_capability_spec(
    *,
    tool_id: str,
    name: str,
    description: str,
    parameters: dict[str, Any],
    category: str = "general",
) -> CapabilitySpec:
    """Map legacy ToolCaller registration shape to CapabilitySpec (audit helper)."""
    return CapabilitySpec(
        id=tool_id,
        name=name,
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        spec={
            "description": description,
            "category": category,
            "parameters": parameters,
            "legacy_tool_caller": True,
        },
        permission="chat:write",
    )
