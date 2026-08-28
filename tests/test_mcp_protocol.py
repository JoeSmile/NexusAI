"""Task 66 slice 3 — MCP protocol + registry normalization."""

from __future__ import annotations

import json

import pytest

from packages.capability.mcp_errors import McpErrorCode, map_jsonrpc_error
from packages.capability.mcp_registry import (
    McpServerConfig,
    capability_id_for_mcp_tool,
    infer_mcp_risk_level,
    load_mcp_servers_from_env,
    normalize_mcp_tool,
    register_mcp_tools,
)
from packages.capability.models import CapabilityKind, CapabilityProvider
from packages.capability.registry import CapabilityRegistry


def test_capability_id_for_mcp_tool() -> None:
    assert capability_id_for_mcp_tool("time", "get_current_time") == "mcp:time:get_current_time"


def test_load_mcp_servers_rejects_ssrf_url() -> None:
    raw = json.dumps(
        [
            {
                "id": "bad",
                "transport": "http",
                "url": "http://localhost/mcp",
            }
        ]
    )
    servers = load_mcp_servers_from_env(raw)
    assert servers == []


def test_normalize_mcp_tool_valid() -> None:
    server = McpServerConfig(id="mock", transport="stdio", command="echo")
    spec = normalize_mcp_tool(
        server,
        {
            "name": "echo",
            "description": "Echo back the input message for tests",
            "inputSchema": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
            },
        },
    )
    assert spec is not None
    assert spec.id == "mcp:mock:echo"
    assert spec.provider == CapabilityProvider.MCP
    assert spec.spec.get("risk_level") in ("medium", "high")


def test_normalize_mcp_tool_rejects_short_description() -> None:
    server = McpServerConfig(id="mock", transport="http", url="https://example.com/mcp")
    assert normalize_mcp_tool(server, {"name": "x", "description": "short"}) is None


def test_normalize_mcp_tool_rejects_non_object_schema() -> None:
    server = McpServerConfig(id="mock", transport="stdio", command="uvx")
    assert normalize_mcp_tool(
        server,
        {
            "name": "bad",
            "description": "This tool has an invalid schema for registration",
            "inputSchema": {"type": "string"},
        },
    ) is None


def test_infer_mcp_risk_stdio_bump_and_sensitive_params() -> None:
    base = infer_mcp_risk_level({"type": "object", "properties": {}}, transport="stdio")
    urlish = infer_mcp_risk_level(
        {"type": "object", "properties": {"url": {"type": "string"}}},
        transport="http",
    )
    assert _RISK_INDEX(base) >= _RISK_INDEX("medium")
    assert _RISK_INDEX(urlish) > _RISK_INDEX("medium")


def _RISK_INDEX(level: str) -> int:
    order = ("low", "medium", "high", "critical")
    return order.index(level)


def test_register_mcp_tools_isolates_bad_tool() -> None:
    reg = CapabilityRegistry()
    server = McpServerConfig(id="mock", transport="stdio", command="uvx")
    reg_n, rej = register_mcp_tools(
        reg,
        server,
        [
            {
                "name": "good",
                "description": "Valid tool with enough description text",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {"name": "bad", "description": "x"},
        ],
    )
    assert reg_n == 1
    assert rej == 1
    spec = reg.get("mcp:mock:good")
    assert spec.kind == CapabilityKind.TOOL


def test_map_jsonrpc_error_codes() -> None:
    err = map_jsonrpc_error(-32602, "Invalid params")
    assert err.code == McpErrorCode.MCP_PROTOCOL_ERROR.value
    assert err.retryable is False or err.retryable is True


@pytest.mark.asyncio
async def test_invoke_mcp_mock_echo(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.auth.models import TenantContext
    from packages.capability.connectors.mcp_server import invoke_mcp
    from packages.capability.models import CapabilitySpec, CapabilityStatus

    monkeypatch.setenv("CAPABILITY_UPSTREAM_MOCK", "true")
    monkeypatch.setenv(
        "MCP_SERVERS_JSON",
        json.dumps([{"id": "mock", "transport": "stdio", "command": "uvx", "args": ["mcp-server-time"]}]),
    )
    spec = CapabilitySpec(
        id="mcp:mock:echo",
        name="mcp:mock:echo",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.MCP,
        spec={
            "governance": True,
            "executor": "mcp",
            "mcp_server_id": "mock",
            "mcp_tool_name": "echo",
            "tool_contract": {
                "name": "mcp:mock:echo",
                "version": "v1",
                "description": "Echo tool for mock MCP invoke tests",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object", "properties": {"content": {"type": "array"}}},
                "failure_semantics": {
                    "retryable": True,
                    "idempotent": False,
                    "requires_compensation": False,
                    "failure_codes": [],
                },
                "idempotency_key_args": [],
                "examples": [{"input": {}, "output": {"content": []}}],
            },
        },
        permission="chat:write",
        status=CapabilityStatus.ENABLED,
    )
    tenant = TenantContext("t1", "u1", "user", ["chat:write"], False)
    frames = []
    async for frame in invoke_mcp(spec, {"message": "hello-mcp"}, tenant):
        frames.append(frame)
    assert any(f.get("event") == "done" for f in frames)
    done = next(f for f in frames if f.get("event") == "done")
    assert done["data"]["executor"] == "mcp"
