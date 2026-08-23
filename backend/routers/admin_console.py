"""Admin console API — tools/MCP/skills/guardrails management (Task 67)."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.core.audit import write_audit_sync
from backend.core.auth.models import TenantContext
from backend.core.capability.admin_store import (
    update_capability_spec_body,
    update_capability_status,
)
from backend.core.capability.console_access import (
    can_mutate_exec_policy,
    can_mutate_tenant_allowlist,
    can_mutate_tool_status,
    is_console_super_admin,
    require_console_reader,
    require_console_super_admin,
)
from backend.core.capability.errors import CapabilityNotFoundError
from backend.core.capability.exec_policy import resolve_exec_policy
from backend.core.capability.invoke import capability_visible_to
from backend.core.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
    CapabilityStatus,
)
from backend.core.capability.registry import get_capability_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/console", tags=["admin-console"])

from backend.routers.admin_console_guardrails import router as _guardrails_router  # noqa: E402
from backend.routers.admin_console_mcp import router as _mcp_router  # noqa: E402
from backend.routers.admin_console_skills import router as _skills_router  # noqa: E402

router.include_router(_mcp_router)
router.include_router(_skills_router)
router.include_router(_guardrails_router)

_SECRET_SPEC_KEYS = frozenset(
    {"api_key", "api_key_ref", "headers", "secrets", "password", "token"}
)


class StatusPatch(BaseModel):
    status: str = Field(..., pattern="^(enabled|disabled)$")


class TenantAllowlistPatch(BaseModel):
    tenant_ids: list[str] = Field(default_factory=list)


class ExecPolicyPatch(BaseModel):
    timeout_s: float | None = None
    hard_kill_timeout_s: float | None = None
    max_retries: int | None = None
    rate_limit_per_min: int | None = None
    isolation_mode: str | None = None
    max_payload_bytes: int | None = None
    max_concurrent_mcp_subprocess: int | None = None


def _audit_console_tool_change(
    tenant: TenantContext,
    *,
    capability_id: str,
    op: str,
    payload: dict[str, Any],
) -> None:
    write_audit_sync(
        {
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id or "admin",
            "action": "admin.console_tool",
            "trace_id": f"console-tool:{uuid.uuid4().hex[:16]}",
            "input_text": capability_id[:200],
            "output_text": json.dumps({"op": op, **payload}, ensure_ascii=False)[:4000],
            "decision_explain": json.dumps(
                {"op": op, "capability_id": capability_id},
                ensure_ascii=False,
            ),
        }
    )


def _redact_spec(spec_body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in spec_body.items() if k not in _SECRET_SPEC_KEYS}


def _infer_supply_origin(spec: CapabilitySpec) -> str:
    nested = dict(spec.spec or {})
    explicit = str(nested.get("supply_origin") or "").strip().lower()
    if explicit:
        return explicit
    executor = str(nested.get("executor") or "").strip().lower()
    if spec.provider == CapabilityProvider.MCP:
        return "mcp"
    if executor == "builtin":
        return "builtin"
    if nested.get("skill_asset_id") or str(spec.id).startswith("skill:"):
        return "skill"
    return "other"


def _tool_domain(spec: CapabilitySpec) -> str:
    nested = dict(spec.spec or {})
    tags = nested.get("tags") or []
    if isinstance(tags, list) and tags:
        return str(tags[0])
    parts = spec.id.split(":")
    if len(parts) >= 2:
        return parts[1]
    return spec.kind.value


def _tool_admin_summary(spec: CapabilitySpec) -> dict[str, Any]:
    nested = dict(spec.spec or {})
    contract = dict(nested.get("tool_contract") or {})
    return {
        "id": spec.id,
        "name": spec.name,
        "kind": spec.kind.value,
        "provider": spec.provider.value,
        "status": spec.status.value,
        "permission": spec.permission or "chat:write",
        "tenant_id": spec.tenant_id,
        "risk_level": str(nested.get("risk_level") or "medium"),
        "supply_origin": _infer_supply_origin(spec),
        "domain": _tool_domain(spec),
        "executor": str(nested.get("executor") or ""),
        "requires_approval": bool(nested.get("requires_approval")),
        "tenant_allowlist": list(nested.get("tenant_allowlist") or []),
        "description": str(contract.get("description") or nested.get("description") or spec.name),
        "exec_policy": resolve_exec_policy(nested).to_dict(),
    }


def _tool_admin_detail(spec: CapabilitySpec) -> dict[str, Any]:
    nested = dict(spec.spec or {})
    contract = dict(nested.get("tool_contract") or {})
    return {
        **_tool_admin_summary(spec),
        "spec": _redact_spec(nested),
        "tool_contract": contract,
        "param_spec": dict(spec.param_spec) if spec.param_spec else None,
        "cost_model": dict(spec.cost_model or {}),
    }


def _visible_tools_for_tenant(
    tenant: TenantContext,
    *,
    include_disabled: bool,
) -> list[CapabilitySpec]:
    reg = get_capability_registry()
    specs = reg.list(kind=CapabilityKind.TOOL, include_disabled=include_disabled)
    if is_console_super_admin(tenant):
        return specs
    return [s for s in specs if capability_visible_to(s, tenant)]


def _get_tool_or_404(capability_id: str) -> CapabilitySpec:
    try:
        return get_capability_registry().get(capability_id, require_enabled=False)
    except CapabilityNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "CAP_001", "message": "capability_not_found"},
        ) from exc


def _assert_tool_readable(spec: CapabilitySpec, tenant: TenantContext) -> None:
    if spec.kind != CapabilityKind.TOOL:
        raise HTTPException(
            status_code=404,
            detail={"code": "CAP_001", "message": "not_a_tool"},
        )
    if not is_console_super_admin(tenant) and not capability_visible_to(spec, tenant):
        raise HTTPException(
            status_code=404,
            detail={"code": "CAP_001", "message": "capability_not_found"},
        )


@router.get("/tools")
async def list_console_tools(
    tenant: TenantContext = Depends(require_console_reader),
    q: str | None = Query(None),
    risk: str | None = Query(None),
    source: str | None = Query(None),
    status: str | None = Query(None),
    domain: str | None = Query(None),
    include_disabled: bool = Query(True),
) -> dict[str, Any]:
    """Admin tool list with contract/risk/ExecPolicy summary."""
    specs = _visible_tools_for_tenant(tenant, include_disabled=include_disabled)
    items = [_tool_admin_summary(s) for s in specs]

    if q:
        needle = q.strip().lower()
        items = [
            i
            for i in items
            if needle in i["id"].lower()
            or needle in i["name"].lower()
            or needle in i["description"].lower()
        ]
    if risk:
        items = [i for i in items if i["risk_level"] == risk.strip().lower()]
    if source:
        items = [i for i in items if i["supply_origin"] == source.strip().lower()]
    if status:
        items = [i for i in items if i["status"] == status.strip().lower()]
    if domain:
        needle = domain.strip().lower()
        items = [i for i in items if i["domain"].lower() == needle]

    return {"items": items, "total": len(items)}


@router.get("/tools/{capability_id}")
async def get_console_tool(
    capability_id: str,
    tenant: TenantContext = Depends(require_console_reader),
) -> dict[str, Any]:
    spec = _get_tool_or_404(capability_id)
    _assert_tool_readable(spec, tenant)
    return _tool_admin_detail(spec)


@router.patch("/tools/{capability_id}/status")
async def patch_tool_status(
    capability_id: str,
    body: StatusPatch,
    tenant: TenantContext = Depends(require_console_reader),
) -> dict[str, Any]:
    if not can_mutate_tool_status(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_002", "message": "super_admin_required"},
        )
    spec = _get_tool_or_404(capability_id)
    _assert_tool_readable(spec, tenant)
    new_status = CapabilityStatus(body.status)
    updated = update_capability_status(capability_id, new_status)
    _audit_console_tool_change(
        tenant,
        capability_id=capability_id,
        op="status",
        payload={"status": updated.status.value},
    )
    return {"ok": True, "item": _tool_admin_summary(updated)}


@router.put("/tools/{capability_id}/tenant-allowlist")
async def put_tool_tenant_allowlist(
    capability_id: str,
    body: TenantAllowlistPatch,
    tenant: TenantContext = Depends(require_console_reader),
) -> dict[str, Any]:
    if not can_mutate_tenant_allowlist(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_002", "message": "console_access_denied"},
        )
    spec = _get_tool_or_404(capability_id)
    _assert_tool_readable(spec, tenant)

    tenant_ids = [str(t).strip() for t in body.tenant_ids if str(t).strip()]
    if is_console_super_admin(tenant):
        normalized = sorted(set(tenant_ids))
    else:
        # tenant_admin may only ensure their tenant is in/out of allowlist
        current = list((spec.spec or {}).get("tenant_allowlist") or [])
        others = [t for t in current if t != tenant.tenant_id]
        if tenant.tenant_id in tenant_ids:
            normalized = sorted(set(others + [tenant.tenant_id]))
        else:
            normalized = sorted(set(others))

    updated = update_capability_spec_body(
        capability_id,
        spec_patch={"tenant_allowlist": normalized},
    )
    return {"ok": True, "tenant_allowlist": normalized, "item": _tool_admin_summary(updated)}


@router.put("/tools/{capability_id}/exec-policy")
async def put_tool_exec_policy(
    capability_id: str,
    body: ExecPolicyPatch,
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    if not can_mutate_exec_policy(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_002", "message": "super_admin_required"},
        )
    spec = _get_tool_or_404(capability_id)
    _assert_tool_readable(spec, tenant)

    nested = dict(spec.spec or {})
    current = resolve_exec_policy(nested).to_dict()
    patch = body.model_dump(exclude_none=True)
    merged = {**current, **patch}
    updated = update_capability_spec_body(
        capability_id,
        spec_patch={"exec_policy": merged},
    )
    return {
        "ok": True,
        "exec_policy": resolve_exec_policy(updated.spec or {}).to_dict(),
        "item": _tool_admin_summary(updated),
    }


@router.get("/health")
async def console_health(
    tenant: TenantContext = Depends(require_console_reader),
) -> dict[str, Any]:
    return {
        "ok": True,
        "role": tenant.role,
        "tenant_id": tenant.tenant_id,
        "super_admin": is_console_super_admin(tenant),
    }
