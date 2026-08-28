"""Task 66 MCP Phase 2 — subprocess quota, versioned snapshots, pid audit."""

from __future__ import annotations

import json

import pytest

from backend.core.capability.exec_policy import global_default_exec_policy, resolve_exec_policy
from backend.core.capability.mcp_registry import (
    McpServerConfig,
    normalize_mcp_tool,
    register_mcp_tools,
)
from backend.core.capability.mcp_semaphore import reset_mcp_semaphores_for_tests, stdio_spawn_limit
from backend.core.capability.mcp_snapshots import (
    get_mcp_snapshot_registry,
    reset_mcp_snapshot_registry_for_tests,
)
from backend.core.capability.models import CapabilityStatus
from backend.core.capability.registry import CapabilityRegistry


def _valid_tool(name: str) -> dict:
    return {
        "name": name,
        "description": f"Valid tool {name} with enough description text",
        "inputSchema": {"type": "object", "properties": {}},
    }


def test_exec_policy_mcp_subprocess_field() -> None:
    base = global_default_exec_policy()
    assert base.max_concurrent_mcp_subprocess >= 1
    overridden = resolve_exec_policy({"exec_policy": {"max_concurrent_mcp_subprocess": 2}})
    assert overridden.max_concurrent_mcp_subprocess == 2


def test_stdio_spawn_limit_reads_exec_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAPABILITY_MCP_MAX_GLOBAL_CONCURRENCY", raising=False)
    reset_mcp_semaphores_for_tests()
    monkeypatch.setenv("CAPABILITY_MCP_MAX_GLOBAL_CONCURRENCY", "3")
    reset_mcp_semaphores_for_tests()
    assert stdio_spawn_limit() == 3


def test_normalize_mcp_tool_records_snapshot_generation() -> None:
    server = McpServerConfig(id="mock", transport="stdio", command="echo")
    spec = normalize_mcp_tool(server, _valid_tool("echo"), snapshot_generation=7)
    assert spec is not None
    assert spec.spec.get("mcp_snapshot_generation") == 7


def test_snapshot_refresh_retires_removed_tools() -> None:
    reset_mcp_snapshot_registry_for_tests()
    reg = CapabilityRegistry()
    server = McpServerConfig(id="srv", transport="stdio", command="uvx")
    snap = get_mcp_snapshot_registry()

    first = snap.refresh_server_tools(
        reg,
        server.id,
        [_valid_tool("alpha"), _valid_tool("beta")],
        normalize_fn=normalize_mcp_tool,
        server_cfg=server,
    )
    assert first["registered"] == 2
    assert reg.get("mcp:srv:alpha").status == CapabilityStatus.ENABLED
    assert reg.get("mcp:srv:beta").status == CapabilityStatus.ENABLED

    second = snap.refresh_server_tools(
        reg,
        server.id,
        [_valid_tool("alpha")],
        normalize_fn=normalize_mcp_tool,
        server_cfg=server,
    )
    assert second["generation"] == 2
    assert second["retired"] == 1
    beta = reg.get("mcp:srv:beta", require_enabled=False)
    assert beta.status == CapabilityStatus.DISABLED
    assert beta.spec.get("mcp_retired") is True


def test_snapshot_refresh_bumps_generation_without_deleting_active() -> None:
    reset_mcp_snapshot_registry_for_tests()
    reg = CapabilityRegistry()
    server = McpServerConfig(id="srv", transport="http", url="https://example.com/mcp")
    snap = get_mcp_snapshot_registry()

    snap.refresh_server_tools(
        reg,
        server.id,
        [_valid_tool("keep")],
        normalize_fn=normalize_mcp_tool,
        server_cfg=server,
    )
    before = reg.get("mcp:srv:keep")
    snap.refresh_server_tools(
        reg,
        server.id,
        [_valid_tool("keep")],
        normalize_fn=normalize_mcp_tool,
        server_cfg=server,
    )
    after = reg.get("mcp:srv:keep")
    assert after.spec.get("mcp_snapshot_generation") == 2
    assert after.status == CapabilityStatus.ENABLED
    assert before.id == after.id


@pytest.mark.asyncio
async def test_invoke_mcp_mock_has_no_subprocess_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.auth.models import TenantContext
    from backend.core.capability.connectors.mcp_server import invoke_mcp
    from backend.core.capability.models import CapabilityKind, CapabilityProvider, CapabilitySpec

    monkeypatch.setenv("CAPABILITY_UPSTREAM_MOCK", "true")
    monkeypatch.setenv(
        "MCP_SERVERS_JSON",
        json.dumps([{"id": "mock", "transport": "http", "url": "https://example.com/mcp"}]),
    )
    spec = CapabilitySpec(
        id="mcp:mock:echo",
        name="mcp:mock:echo",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.MCP,
        spec={
            "executor": "mcp",
            "mcp_server_id": "mock",
            "mcp_tool_name": "echo",
        },
        permission="chat:write",
    )
    tenant = TenantContext("t1", "u1", "user", ["chat:write"], False)
    frames = []
    async for frame in invoke_mcp(spec, {"message": "hello"}, tenant):
        frames.append(frame)
    done = next(f for f in frames if f.get("event") == "done")
    assert "mcp_subprocess_pid" not in done["data"]


def test_register_mcp_tools_still_works_without_snapshot() -> None:
    reg = CapabilityRegistry()
    server = McpServerConfig(id="mock", transport="stdio", command="uvx")
    reg_n, rej = register_mcp_tools(reg, server, [_valid_tool("legacy")])
    assert reg_n == 1
    assert rej == 0
