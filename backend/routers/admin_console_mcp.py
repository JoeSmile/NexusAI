"""Admin console MCP server routes (Task 67 slice 2)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from packages.auth.models import TenantContext
from backend.core.capability.connectors.mcp_server import (
    list_server_tools,
    mcp_server_runtime_status,
)
from backend.core.capability.console_access import require_console_super_admin
from backend.core.capability.mcp_errors import McpError
from backend.core.capability.mcp_registry import (
    capability_id_for_mcp_tool,
    normalize_mcp_tool,
)
from backend.core.capability.mcp_store import (
    delete_mcp_server_record,
    get_mcp_server_record,
    list_mcp_server_records,
    save_mcp_server_probe,
    upsert_mcp_server_record,
)
from backend.core.capability.registry import get_capability_registry
from backend.core.security.url_guard import UrlValidationError

router = APIRouter()


class McpServerBody(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    tenant_id: str = "*"
    transport: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    allow_pass_user_context: bool = False
    timeout_s: float = 30.0


class McpServerUpdateBody(BaseModel):
    tenant_id: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    enabled: bool | None = None
    allow_pass_user_context: bool | None = None
    timeout_s: float | None = None


class ImportMcpToolsBody(BaseModel):
    tool_names: list[str] = Field(default_factory=list)
    risk_overrides: dict[str, str] = Field(default_factory=dict)


def _tool_preview(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    props = schema.get("properties") if isinstance(schema, dict) else {}
    return {
        "name": str(tool.get("name") or ""),
        "description": str(tool.get("description") or "")[:240],
        "property_count": len(props) if isinstance(props, dict) else 0,
        "input_schema_type": str(schema.get("type") or "object") if isinstance(schema, dict) else "object",
    }


def _server_view(rec, *, include_runtime: bool = True) -> dict[str, Any]:
    payload = rec.to_public_dict(mask_secrets=True)
    if include_runtime:
        runtime = mcp_server_runtime_status(rec.id)
        payload["runtime"] = runtime
        probe = payload.get("last_probe") or {}
        if probe.get("status") == "failed":
            payload["display_status"] = "failed"
        elif runtime.get("circuit_state") == "open":
            payload["display_status"] = "circuit_open"
        elif probe.get("status") == "connected":
            payload["display_status"] = "connected"
        else:
            payload["display_status"] = runtime.get("connection_status", "unknown")
    return payload


def _require_db_server(server_id: str):
    rec = get_mcp_server_record(server_id)
    if rec is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "MCP_NOT_CONFIGURED", "message": "mcp_server_not_found"},
        )
    return rec


@router.get("/mcp/servers")
async def list_mcp_servers(
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    items = [_server_view(rec) for rec in list_mcp_server_records()]
    return {"items": items, "total": len(items)}


@router.post("/mcp/servers")
async def create_mcp_server(
    body: McpServerBody,
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    if get_mcp_server_record(body.id) is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "REQ_INVALID", "message": "mcp_server_exists"},
        )
    try:
        rec = upsert_mcp_server_record(
            server_id=body.id.strip(),
            tenant_id=body.tenant_id,
            transport=body.transport,
            command=body.command,
            args=body.args,
            env=body.env,
            url=body.url,
            headers=body.headers,
            enabled=body.enabled,
            allow_pass_user_context=body.allow_pass_user_context,
            timeout_s=body.timeout_s,
            merge_headers=False,
        )
    except (UrlValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "REQ_INVALID", "message": str(exc)},
        ) from exc
    return {"ok": True, "item": _server_view(rec)}


@router.get("/mcp/servers/{server_id}")
async def get_mcp_server(
    server_id: str,
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    rec = _require_db_server(server_id)
    return _server_view(rec)


@router.put("/mcp/servers/{server_id}")
async def update_mcp_server(
    server_id: str,
    body: McpServerUpdateBody,
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    existing = _require_db_server(server_id)
    patch = body.model_dump(exclude_none=True)
    try:
        rec = upsert_mcp_server_record(
            server_id=server_id,
            tenant_id=str(patch.get("tenant_id", existing.tenant_id)),
            transport=str(patch.get("transport", existing.transport)),
            command=str(patch.get("command", existing.command)),
            args=list(patch.get("args", existing.args)),
            env=dict(patch.get("env", existing.env)),
            url=str(patch.get("url", existing.url)),
            headers=dict(patch.get("headers", existing.headers)),
            enabled=bool(patch.get("enabled", existing.enabled)),
            allow_pass_user_context=bool(
                patch.get("allow_pass_user_context", existing.allow_pass_user_context)
            ),
            timeout_s=float(patch.get("timeout_s", existing.timeout_s)),
            merge_headers=True,
        )
    except (UrlValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "REQ_INVALID", "message": str(exc)},
        ) from exc
    return {"ok": True, "item": _server_view(rec)}


@router.delete("/mcp/servers/{server_id}")
async def delete_mcp_server(
    server_id: str,
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    _require_db_server(server_id)
    if not delete_mcp_server_record(server_id):
        raise HTTPException(
            status_code=404,
            detail={"code": "MCP_NOT_CONFIGURED", "message": "mcp_server_not_found"},
        )
    return {"ok": True, "id": server_id}


@router.post("/mcp/servers/{server_id}/test")
async def test_mcp_server(
    server_id: str,
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    rec = _require_db_server(server_id)
    cfg = rec.to_config()
    runtime = mcp_server_runtime_status(server_id)
    try:
        tools = await list_server_tools(cfg)
        previews = [_tool_preview(t) for t in tools if isinstance(t, dict)]
        probe = {
            "status": "connected",
            "tool_count": len(previews),
            "tools": previews,
        }
        save_mcp_server_probe(server_id, probe)
        return {
            "ok": True,
            "status": "connected",
            "tool_count": len(previews),
            "tools": previews,
            "runtime": runtime,
        }
    except McpError as exc:
        probe = {"status": "failed", "error": exc.to_dict()}
        save_mcp_server_probe(server_id, probe)
        return {
            "ok": False,
            "status": "failed",
            "error": exc.to_dict(),
            "runtime": runtime,
        }


@router.post("/mcp/servers/{server_id}/import-tools")
async def import_mcp_tools(
    server_id: str,
    body: ImportMcpToolsBody,
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    rec = _require_db_server(server_id)
    cfg = rec.to_config()
    if not body.tool_names:
        raise HTTPException(
            status_code=422,
            detail={"code": "REQ_INVALID", "message": "tool_names_required"},
        )

    try:
        tools = await list_server_tools(cfg)
    except McpError as exc:
        raise HTTPException(
            status_code=502,
            detail=exc.to_dict(),
        ) from exc

    selected = {name.strip() for name in body.tool_names if name.strip()}
    registry = get_capability_registry()
    registered: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "")
        if name not in selected:
            continue
        override = body.risk_overrides.get(name)
        spec = normalize_mcp_tool(cfg, tool, risk_override=override)
        if spec is None:
            rejected.append({"name": name, "reason": "normalize_rejected"})
            continue
        try:
            registry.register(spec)
            registered.append(
                {
                    "id": spec.id,
                    "name": name,
                    "risk_level": spec.spec.get("risk_level"),
                    "requires_approval": bool(spec.spec.get("requires_approval")),
                }
            )
        except Exception as exc:
            rejected.append({"name": name, "reason": str(exc)})

    return {
        "ok": True,
        "registered": registered,
        "rejected": rejected,
        "preview": [
            {
                "id": capability_id_for_mcp_tool(server_id, name),
                "name": name,
                "risk_override": body.risk_overrides.get(name),
            }
            for name in sorted(selected)
        ],
    }
