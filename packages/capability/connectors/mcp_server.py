"""MCP server connector — stdio + streamable HTTP (Task 66 slice 3)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from backend.core.circuit_breaker import CircuitBreaker, CircuitState
from packages.security.url_guard import UrlValidationError, validate_base_url
from packages.auth.models import TenantContext
from packages.capability.errors import CapabilityUpstreamError
from packages.capability.mcp_errors import McpError, McpErrorCode
from packages.capability.mcp_registry import (
    McpServerConfig,
    get_mcp_server_config,
    parse_capability_mcp_binding,
)
from packages.capability.mcp_semaphore import mcp_call_semaphore, stdio_spawn_semaphore
from packages.capability.models import CapabilitySpec

logger = logging.getLogger(__name__)

_BREAKERS: dict[str, CircuitBreaker] = {}


@dataclass
class McpSessionHandle:
    session: Any
    subprocess_pid: int | None = None

_MOCK_TOOLS: list[dict[str, Any]] = [
    {
        "name": "echo",
        "description": "Echo back the input message for connector tests",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
    {
        "name": "calculator",
        "description": "Add two numbers for parameter validation tests",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    },
    {
        "name": "slow",
        "description": "Sleep longer than timeout to test MCP_TIMEOUT handling",
        "inputSchema": {"type": "object", "properties": {"seconds": {"type": "number"}}},
    },
    {
        "name": "crash",
        "description": "Simulate server crash on invocation for error tests",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _mock_enabled() -> bool:
    if os.getenv("CAPABILITY_UPSTREAM_MOCK", "").strip().lower() in ("1", "true", "yes"):
        return True
    return os.getenv("LLM_PROVIDER", "").strip().lower() == "mock"


def _breaker(server_id: str) -> CircuitBreaker:
    if server_id not in _BREAKERS:
        _BREAKERS[server_id] = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            name=f"mcp:{server_id}",
        )
    return _BREAKERS[server_id]


def _mock_call_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "crash":
        raise McpError(
            code=McpErrorCode.MCP_SERVER_CRASH.value,
            message="mock_server_crash",
        )
    if tool_name == "slow":
        raise McpError(
            code=McpErrorCode.MCP_TIMEOUT.value,
            message="mock_slow_tool",
            retryable=True,
        )
    if tool_name == "calculator":
        a = float(arguments.get("a", 0))
        b = float(arguments.get("b", 0))
        return {"content": [{"type": "text", "text": str(a + b)}], "isError": False}
    message = str(arguments.get("message") or arguments)
    return {"content": [{"type": "text", "text": message}], "isError": False}


def _tool_result_to_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "content"):
        content = []
        for block in result.content or []:
            if hasattr(block, "model_dump"):
                content.append(block.model_dump())
            elif isinstance(block, dict):
                content.append(block)
            else:
                content.append({"type": "text", "text": str(block)})
        return {
            "content": content,
            "isError": bool(getattr(result, "isError", False)),
        }
    return {"content": [{"type": "text", "text": str(result)}], "isError": False}


def _sanitize_tool_arguments(
    arguments: dict[str, Any],
    *,
    tenant: TenantContext,
    allow_pass_user_context: bool,
) -> dict[str, Any]:
    if allow_pass_user_context:
        return dict(arguments)
    blocked = frozenset({"user_id", "tenant_id", "api_key", "token", "password"})
    return {k: v for k, v in arguments.items() if k not in blocked and v is not None}


@asynccontextmanager
async def mcp_session(server: McpServerConfig):
    """Open MCP ClientSession for stdio or HTTP transport."""
    if _mock_enabled():
        yield McpSessionHandle(session=None, subprocess_pid=None)
        return

    timeout = max(1.0, float(server.timeout_s))
    if server.transport == "http":
        url = validate_base_url(server.url)
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(url, headers=server.headers or None) as streams:
            from mcp import ClientSession

            read, write, _ = streams
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=timeout)
                yield McpSessionHandle(session=session, subprocess_pid=None)
        return

    if not server.command:
        raise McpError(
            code=McpErrorCode.MCP_NOT_CONFIGURED.value,
            message="stdio_command_missing",
        )

    from mcp import ClientSession, StdioServerParameters

    from packages.capability.connectors.mcp_stdio_tracked import tracked_stdio_client

    params = StdioServerParameters(
        command=server.command,
        args=list(server.args),
        env=server.env or None,
    )
    async with stdio_spawn_semaphore():
        async with tracked_stdio_client(params, errlog=sys.stderr) as (read, write, pid):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=timeout)
                yield McpSessionHandle(session=session, subprocess_pid=pid)


def mcp_server_runtime_status(server_id: str) -> dict[str, Any]:
    brk = _breaker(server_id)
    state = brk.state
    label = "connected"
    if state == CircuitState.OPEN:
        label = "circuit_open"
    elif state == CircuitState.HALF_OPEN:
        label = "half_open"
    return {
        "circuit_state": state.value,
        "connection_status": label,
    }


async def list_server_tools(server: McpServerConfig) -> list[dict[str, Any]]:
    brk = _breaker(server.id)
    if brk.state == CircuitState.OPEN:
        raise McpError(
            code=McpErrorCode.CIRCUIT_OPEN.value,
            message="circuit_open",
            retryable=False,
        )
    if _mock_enabled():
        return list(_MOCK_TOOLS)
    try:
        async with mcp_call_semaphore():
            async with mcp_session(server) as handle:
                assert handle.session is not None
                result = await asyncio.wait_for(
                    handle.session.list_tools(),
                    timeout=max(1.0, server.timeout_s),
                )
        tools_raw = getattr(result, "tools", None) or []
        tools: list[dict[str, Any]] = []
        for t in tools_raw:
            if hasattr(t, "model_dump"):
                tools.append(t.model_dump())
            elif isinstance(t, dict):
                tools.append(t)
        brk._on_success()
        return tools
    except McpError:
        brk._on_failure()
        raise
    except TimeoutError as exc:
        brk._on_failure()
        raise McpError(
            code=McpErrorCode.MCP_TIMEOUT.value,
            message="tools_list_timeout",
            inner_error=str(exc),
        ) from exc
    except Exception as exc:
        brk._on_failure()
        raise McpError(
            code=McpErrorCode.MCP_SERVER_CRASH.value,
            message="tools_list_failed",
            inner_error=str(exc),
        ) from exc


async def call_server_tool(
    server: McpServerConfig,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    tenant: TenantContext,
) -> dict[str, Any]:
    brk = _breaker(server.id)
    if brk.state == CircuitState.OPEN:
        raise McpError(
            code=McpErrorCode.CIRCUIT_OPEN.value,
            message="circuit_open",
            retryable=False,
        )
    safe_args = _sanitize_tool_arguments(
        arguments,
        tenant=tenant,
        allow_pass_user_context=server.allow_pass_user_context,
    )
    if _mock_enabled():
        try:
            out = _mock_call_tool(tool_name, safe_args)
            brk._on_success()
            return out
        except McpError:
            brk._on_failure()
            raise

    subprocess_pid: int | None = None
    try:
        async with mcp_call_semaphore():
            async with mcp_session(server) as handle:
                assert handle.session is not None
                subprocess_pid = handle.subprocess_pid
                result = await asyncio.wait_for(
                    handle.session.call_tool(tool_name, safe_args),
                    timeout=max(1.0, server.timeout_s),
                )
        out = _tool_result_to_dict(result)
        if subprocess_pid is not None:
            out["mcp_subprocess_pid"] = subprocess_pid
        brk._on_success()
        return out
    except McpError:
        brk._on_failure()
        raise
    except TimeoutError as exc:
        brk._on_failure()
        raise McpError(
            code=McpErrorCode.MCP_TIMEOUT.value,
            message="tools_call_timeout",
            inner_error=str(exc),
        ) from exc
    except UrlValidationError as exc:
        brk._on_failure()
        raise McpError(
            code=McpErrorCode.MCP_PROTOCOL_ERROR.value,
            message=exc.code,
            inner_error=str(exc),
            retryable=False,
        ) from exc
    except Exception as exc:
        brk._on_failure()
        raise McpError(
            code=McpErrorCode.MCP_SERVER_CRASH.value,
            message="tools_call_failed",
            inner_error=str(exc),
        ) from exc


def _payload_to_arguments(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("arguments"), dict):
        return dict(payload["arguments"])
    if isinstance(payload.get("inputs"), dict):
        return dict(payload["inputs"])
    out = {k: v for k, v in payload.items() if k not in ("message", "query", "user_id")}
    for key in ("message", "query"):
        if payload.get(key) is not None:
            out.setdefault("message", str(payload[key]))
    return out


async def invoke_mcp(
    spec: CapabilitySpec,
    payload: dict[str, Any],
    tenant: TenantContext,
) -> AsyncIterator[dict[str, Any]]:
    """Invoke MCP tool and yield invoke event frames."""
    server_id, tool_name = parse_capability_mcp_binding(spec)
    server = get_mcp_server_config(server_id)
    arguments = _payload_to_arguments(payload if isinstance(payload, dict) else {})

    try:
        result = await call_server_tool(server, tool_name, arguments, tenant=tenant)
    except McpError as exc:
        yield {
            "event": "error",
            "data": exc.to_dict(),
            "cost_source": "invoke",
        }
        raise CapabilityUpstreamError(
            message=exc.code,
            detail=json.dumps(exc.to_dict(), ensure_ascii=False),
        ) from exc

    subprocess_pid = result.pop("mcp_subprocess_pid", None)
    if subprocess_pid is not None:
        from packages.audit import write_audit_sync
        from packages.audit_context import get_audit_lineage

        lineage = get_audit_lineage()
        audit_payload = {
            "supply_origin": "mcp",
            "mcp_server_id": server_id,
            "mcp_tool_name": tool_name,
            "mcp_subprocess_pid": subprocess_pid,
            "capability_id": spec.id,
        }
        write_audit_sync(
            {
                "tenant_id": tenant.tenant_id,
                "user_id": tenant.user_id,
                "action": "capability.mcp_subprocess",
                "trace_id": lineage.trace_id or spec.id,
                "parent_trace_id": lineage.parent_trace_id,
                "tool_use_id": lineage.tool_use_id,
                "input_text": spec.id[:200],
                "output_text": json.dumps(audit_payload, ensure_ascii=False)[:4000],
                "decision_explain": json.dumps(audit_payload, ensure_ascii=False),
                "model": spec.id,
            }
        )

    text = json.dumps(result, ensure_ascii=False, default=str)
    chunk = 48
    for i in range(0, max(len(text), 1), chunk):
        part = text[i : i + chunk] if text else ""
        if part:
            yield {"event": "token", "data": part, "cost_source": "invoke"}
    done_data: dict[str, Any] = {
        "capability_id": spec.id,
        "kind": spec.kind.value,
        "executor": "mcp",
        "mcp_server_id": server_id,
        "mcp_tool_name": tool_name,
        "result": result,
        "supply_origin": "mcp",
    }
    if subprocess_pid is not None:
        done_data["mcp_subprocess_pid"] = subprocess_pid
    yield {
        "event": "done",
        "data": done_data,
        "cost_source": "invoke",
    }
