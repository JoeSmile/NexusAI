"""MCP server registry — config, tool normalization, CapabilityRegistry sync (Task 66)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from backend.core.security.url_guard import UrlValidationError, validate_base_url
from packages.capability.contract import stub_contract_dict
from packages.capability.errors import CapabilityNotFoundError
from packages.capability.mcp_errors import McpError, McpErrorCode
from packages.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
    CapabilityStatus,
)
from packages.capability.registry import CapabilityRegistry

logger = logging.getLogger(__name__)

_RISK_ORDER = ("low", "medium", "high", "critical")
_SENSITIVE_PARAM_HINTS = frozenset({"path", "url", "sql", "command", "file", "exec"})


@dataclass
class McpServerConfig:
    id: str
    transport: str = "stdio"  # stdio | http
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    allow_pass_user_context: bool = False
    timeout_s: float = 30.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> McpServerConfig:
        return cls(
            id=str(raw["id"]),
            transport=str(raw.get("transport") or "stdio").strip().lower(),
            command=str(raw.get("command") or ""),
            args=[str(a) for a in (raw.get("args") or [])],
            env={str(k): str(v) for k, v in dict(raw.get("env") or {}).items()},
            url=str(raw.get("url") or ""),
            headers={str(k): str(v) for k, v in dict(raw.get("headers") or {}).items()},
            enabled=bool(raw.get("enabled", True)),
            allow_pass_user_context=bool(raw.get("allow_pass_user_context", False)),
            timeout_s=float(raw.get("timeout_s") or 30),
        )


def load_mcp_servers() -> list[McpServerConfig]:
    """Merged MCP server config: env + DB (DB wins on same id)."""
    from packages.capability.mcp_store import load_all_mcp_servers

    return load_all_mcp_servers()


def load_mcp_servers_from_env(raw: str | None = None) -> list[McpServerConfig]:
    text = (raw if raw is not None else os.getenv("MCP_SERVERS_JSON", "")).strip()
    if not text or text == "[]":
        return []
    try:
        items = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("MCP_SERVERS_JSON invalid: %s", exc)
        return []
    if not isinstance(items, list):
        return []
    out: list[McpServerConfig] = []
    for item in items:
        if not isinstance(item, dict) or "id" not in item:
            continue
        try:
            cfg = McpServerConfig.from_dict(item)
            if cfg.transport == "http" and cfg.url:
                validate_base_url(cfg.url)
            out.append(cfg)
        except (UrlValidationError, KeyError, ValueError) as exc:
            logger.warning("skip mcp server %s: %s", item.get("id"), exc)
    return out


def capability_id_for_mcp_tool(server_id: str, tool_name: str) -> str:
    return f"mcp:{server_id}:{tool_name}"


def _bump_risk(level: str, steps: int = 1) -> str:
    try:
        idx = _RISK_ORDER.index(level)
    except ValueError:
        idx = 1
    return _RISK_ORDER[min(len(_RISK_ORDER) - 1, idx + steps)]


def infer_mcp_risk_level(
    input_schema: dict[str, Any],
    *,
    transport: str,
    override: str | None = None,
) -> str:
    if override:
        return str(override).strip().lower()
    level = "medium"  # supply_origin=mcp default
    props = input_schema.get("properties") if isinstance(input_schema, dict) else {}
    if isinstance(props, dict):
        for key in props:
            if str(key).lower() in _SENSITIVE_PARAM_HINTS:
                level = _bump_risk(level)
                break
    if transport == "stdio":
        level = _bump_risk(level)
    return level


def normalize_mcp_tool(
    server: McpServerConfig,
    tool: dict[str, Any],
    *,
    snapshot_generation: int | None = None,
    risk_override: str | None = None,
) -> CapabilitySpec | None:
    """Map MCP tool → CapabilitySpec; return None if invalid (isolated reject)."""
    name = str(tool.get("name") or "").strip()
    if not name:
        return None
    description = str(tool.get("description") or "").strip()
    if len(description) < 12:
        logger.debug("mcp tool %s rejected: description too short", name)
        return None
    input_schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    if not isinstance(input_schema, dict) or input_schema.get("type", "object") != "object":
        logger.debug("mcp tool %s rejected: input_schema not object", name)
        return None

    cap_id = capability_id_for_mcp_tool(server.id, name)
    risk = infer_mcp_risk_level(
        input_schema,
        transport=server.transport,
        override=risk_override or tool.get("risk_override"),
    )
    contract = {
        **stub_contract_dict(cap_id),
        "description": description,
        "input_schema": input_schema,
        "output_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "array"},
                "isError": {"type": "boolean"},
            },
        },
        "failure_semantics": {
            "retryable": True,
            "idempotent": False,
            "requires_compensation": False,
            "failure_codes": ["MCP_PROTOCOL_ERROR", "MCP_TIMEOUT"],
        },
        "examples": [
            {
                "input": {},
                "output": {"content": [], "isError": False},
            }
        ],
    }
    spec_body: dict[str, Any] = {
        "governance": True,
        "executor": "mcp",
        "mcp_server_id": server.id,
        "mcp_tool_name": name,
        "supply_origin": "mcp",
        "risk_level": risk,
        "transport": server.transport,
        "allow_pass_user_context": server.allow_pass_user_context,
        "tool_contract": contract,
        "timeout_s": server.timeout_s,
    }
    if risk in ("high", "critical"):
        spec_body["requires_approval"] = True
    if snapshot_generation is not None:
        spec_body["mcp_snapshot_generation"] = snapshot_generation

    return CapabilitySpec(
        id=cap_id,
        name=cap_id,
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.MCP,
        spec=spec_body,
        permission="chat:write",
        status=CapabilityStatus.ENABLED if server.enabled else CapabilityStatus.DISABLED,
    )


def register_mcp_tools(
    registry: CapabilityRegistry,
    server: McpServerConfig,
    tools: list[dict[str, Any]],
) -> tuple[int, int]:
    """Register tools from tools/list; returns (registered, rejected)."""
    registered = 0
    rejected = 0
    for tool in tools:
        if not isinstance(tool, dict):
            rejected += 1
            continue
        try:
            spec = normalize_mcp_tool(server, tool)
        except Exception as exc:
            logger.warning("mcp tool normalize failed: %s", exc)
            rejected += 1
            continue
        if spec is None:
            rejected += 1
            continue
        try:
            registry.register(spec)
            registered += 1
        except Exception as exc:
            logger.warning("mcp tool register failed %s: %s", spec.id, exc)
            rejected += 1
    return registered, rejected


def get_mcp_server_config(server_id: str) -> McpServerConfig:
    for cfg in load_mcp_servers():
        if cfg.id == server_id:
            return cfg
    raise McpError(
        code=McpErrorCode.MCP_NOT_CONFIGURED.value,
        message="mcp_server_not_found",
        inner_error=server_id,
        retryable=False,
    )


async def refresh_mcp_servers_from_env(
    registry: CapabilityRegistry,
    *,
    list_tools_fn=None,
) -> dict[str, Any]:
    """Async: load env servers, fetch tools/list, register capabilities."""
    from packages.capability.connectors.mcp_server import list_server_tools

    fetch = list_tools_fn or list_server_tools
    summary: dict[str, Any] = {"servers": [], "registered": 0, "rejected": 0}
    for server in load_mcp_servers():
        if not server.enabled:
            continue
        try:
            tools = fetch(server)
            if hasattr(tools, "__await__"):
                tools = await tools
        except McpError as exc:
            logger.warning("mcp tools/list failed server=%s: %s", server.id, exc.message)
            summary["servers"].append(
                {"id": server.id, "status": "failed", "error": exc.to_dict()}
            )
            continue
        from packages.capability.mcp_snapshots import get_mcp_snapshot_registry

        snap = get_mcp_snapshot_registry()
        snap_result = snap.refresh_server_tools(
            registry,
            server.id,
            tools,
            normalize_fn=normalize_mcp_tool,
            server_cfg=server,
        )
        reg = int(snap_result["registered"])
        rej = int(snap_result["rejected"])
        summary["registered"] += reg
        summary["rejected"] += rej
        summary["servers"].append(
            {
                "id": server.id,
                "status": "connected",
                "registered": reg,
                "rejected": rej,
                "generation": snap_result["generation"],
                "retired": snap_result["retired"],
            }
        )
    return summary


def sync_mcp_servers_from_env(
    registry: CapabilityRegistry,
    *,
    list_tools_fn=None,
) -> dict[str, Any]:
    """Sync wrapper for registry bootstrap (no running event loop)."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            refresh_mcp_servers_from_env(registry, list_tools_fn=list_tools_fn)
        )
    raise RuntimeError("sync_mcp_servers_from_env requires no running event loop")


def parse_capability_mcp_binding(spec: CapabilitySpec) -> tuple[str, str]:
    body = spec.spec if isinstance(spec.spec, dict) else {}
    server_id = str(body.get("mcp_server_id") or "")
    tool_name = str(body.get("mcp_tool_name") or "")
    if not server_id or not tool_name:
        if spec.id.startswith("mcp:"):
            parts = spec.id.split(":", 2)
            if len(parts) == 3:
                server_id = server_id or parts[1]
                tool_name = tool_name or parts[2]
    if not server_id or not tool_name:
        raise CapabilityNotFoundError(
            message="mcp_binding_missing",
            detail=spec.id,
        )
    return server_id, tool_name
