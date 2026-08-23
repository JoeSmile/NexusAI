"""Task 66 slice 3 — MCP governance + security tests."""

from __future__ import annotations

import json

import pytest

from backend.core.auth.models import TenantContext
from backend.core.capability.connectors.mcp_server import _sanitize_tool_arguments
from backend.core.capability.governance_chain import run_governance_chain
from backend.core.capability.mcp_registry import (
    McpServerConfig,
    infer_mcp_risk_level,
    normalize_mcp_tool,
    register_mcp_tools,
)
from backend.core.capability.registry import CapabilityRegistry
from backend.core.errors import ErrorCode, NexusAIException


@pytest.fixture
def tenant_user() -> TenantContext:
    return TenantContext(
        tenant_id="t-mcp",
        user_id="u1",
        role="user",
        extra_permissions=["chat:write"],
        is_cross_tenant=False,
    )


def test_stdio_transport_bumps_risk_above_http() -> None:
    schema = {"type": "object", "properties": {}}
    stdio = infer_mcp_risk_level(schema, transport="stdio")
    http = infer_mcp_risk_level(schema, transport="http")
    order = ("low", "medium", "high", "critical")
    assert order.index(stdio) >= order.index(http)


def test_high_risk_mcp_tool_requires_approval_in_spec() -> None:
    server = McpServerConfig(id="srv", transport="http", url="https://example.com/mcp")
    spec = normalize_mcp_tool(
        server,
        {
            "name": "run_sql",
            "description": "Execute read only SQL queries against allowlisted views",
            "inputSchema": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
            },
        },
    )
    assert spec is not None
    assert spec.spec.get("requires_approval") is True


def test_allow_pass_user_context_default_off() -> None:
    server = McpServerConfig(id="srv", transport="stdio", command="uvx")
    assert server.allow_pass_user_context is False


def test_sanitize_strips_user_context_by_default(tenant_user: TenantContext) -> None:
    server = McpServerConfig(id="srv", transport="stdio", command="uvx")
    out = _sanitize_tool_arguments(
        {"message": "hi", "user_id": "secret", "tenant_id": "secret"},
        tenant=tenant_user,
        allow_pass_user_context=server.allow_pass_user_context,
    )
    assert "user_id" not in out
    assert "tenant_id" not in out
    assert out["message"] == "hi"


def test_governance_blocks_high_risk_mcp_without_approval(tenant_user: TenantContext) -> None:
    from backend.core.capability.invoke import _check_permission

    reg = CapabilityRegistry()
    server = McpServerConfig(id="srv", transport="stdio", command="uvx")
    register_mcp_tools(
        reg,
        server,
        [
            {
                "name": "danger",
                "description": "Dangerous tool that runs shell commands remotely",
                "inputSchema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                },
            },
        ],
    )
    spec = reg.get("mcp:srv:danger")
    with pytest.raises(NexusAIException) as exc:
        run_governance_chain(spec, tenant_user, {}, check_permission=_check_permission)
    assert exc.value.code == ErrorCode.CAP_GOVERNANCE_REQUIRED.value


def test_ssrf_url_rejected_on_server_load() -> None:
    from backend.core.capability.mcp_registry import load_mcp_servers_from_env

    servers = load_mcp_servers_from_env(
        json.dumps(
            [
                {
                    "id": "meta",
                    "transport": "http",
                    "url": "http://169.254.169.254/latest/meta-data/",
                }
            ]
        )
    )
    assert servers == []
