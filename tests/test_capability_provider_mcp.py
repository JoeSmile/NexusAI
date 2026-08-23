"""Task 66 slice 0 — CapabilityProvider.MCP + legacy bridge."""

from __future__ import annotations

from backend.core.capability.local_tool_bridge import legacy_tool_to_capability_spec
from backend.core.capability.models import CapabilityKind, CapabilityProvider
from backend.core.capability.registry import _provider_from_str


def test_mcp_provider_enum() -> None:
    assert CapabilityProvider.MCP.value == "mcp"
    assert _provider_from_str("mcp") == CapabilityProvider.MCP


def test_legacy_tool_bridge_maps_to_tool_kind() -> None:
    spec = legacy_tool_to_capability_spec(
        tool_id="tool:search_memory",
        name="search_memory",
        description="search user memory",
        parameters={"query": {"type": "string"}},
        category="memory",
    )
    assert spec.kind == CapabilityKind.TOOL
    assert spec.provider == CapabilityProvider.NEXUSAI
    assert spec.spec.get("legacy_tool_caller") is True
