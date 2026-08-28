"""Admin console guardrail config routes (Task 67 slice 4)."""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from packages.audit import write_audit_sync
from packages.guardrails.config_store import (
    RISK_LEVELS,
    create_rule,
    delete_rule,
    get_risk_matrix,
    get_rule,
    list_rules,
    update_risk_matrix,
    update_rule,
)
from packages.guardrails.dry_run import dry_run
from packages.auth.models import TenantContext
from packages.capability.console_access import (
    require_console_reader,
    require_console_super_admin,
)

router = APIRouter()


class RuleCreate(BaseModel):
    side: Literal["input", "output"]
    rule_type: Literal[
        "keyword",
        "regex",
        "pii",
        "injection",
        "length",
        "deny_list",
        "sensitive",
        "drift",
        "custom",
    ]
    name: str = Field(..., min_length=1, max_length=120)
    match: str = Field(..., min_length=1, max_length=2000)
    action: Literal["block", "warn", "rewrite", "sanitize"]
    priority: int = Field(50, ge=0, le=1000)
    enabled: bool = True
    description: str = ""


class RulePatch(BaseModel):
    side: Literal["input", "output"] | None = None
    rule_type: Literal[
        "keyword",
        "regex",
        "pii",
        "injection",
        "length",
        "deny_list",
        "sensitive",
        "drift",
        "custom",
    ] | None = None
    name: str | None = Field(None, min_length=1, max_length=120)
    match: str | None = Field(None, min_length=1, max_length=2000)
    action: Literal["block", "warn", "rewrite", "sanitize"] | None = None
    priority: int | None = Field(None, ge=0, le=1000)
    enabled: bool | None = None
    description: str | None = None


class RiskMatrixPatch(BaseModel):
    matrix: dict[str, Literal["allow", "require_approval", "deny"]]


class DryRunRequest(BaseModel):
    side: Literal["input", "output"]
    text: str = Field(..., max_length=20000)
    risk_level: Literal["low", "medium", "high", "critical"] | None = None


def _audit_guardrail_change(
    tenant: TenantContext,
    *,
    op: str,
    subject: str,
    payload: dict[str, Any],
) -> None:
    write_audit_sync(
        {
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id or "admin",
            "action": "admin.guardrail_config",
            "trace_id": f"guardrail:{uuid.uuid4().hex[:16]}",
            "input_text": subject[:200],
            "output_text": json.dumps({"op": op, **payload}, ensure_ascii=False)[:4000],
            "decision_explain": json.dumps({"op": op, "subject": subject}, ensure_ascii=False),
        }
    )


@router.get("/guardrails/rules")
async def list_guardrail_rules(
    tenant: TenantContext = Depends(require_console_super_admin),
    side: str | None = Query(None),
    enabled: bool | None = Query(None),
) -> dict[str, Any]:
    normalized_side = side.strip().lower() if side else None
    if normalized_side and normalized_side not in {"input", "output"}:
        raise HTTPException(
            status_code=400,
            detail={"code": "GRD_400", "message": "invalid_side"},
        )
    rules = list_rules(
        side=normalized_side,  # type: ignore[arg-type]
        enabled_only=enabled is True,
    )
    return {"items": [r.to_dict() for r in rules], "total": len(rules)}


@router.get("/guardrails/rules/{rule_id}")
async def get_guardrail_rule(
    rule_id: str,
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    rule = get_rule(rule_id)
    if rule is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "GRD_404", "message": "not_found"},
        )
    return rule.to_dict()


@router.post("/guardrails/rules")
async def post_guardrail_rule(
    body: RuleCreate,
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    rule = create_rule(
        side=body.side,
        rule_type=body.rule_type,
        name=body.name,
        match=body.match,
        action=body.action,
        priority=body.priority,
        enabled=body.enabled,
        description=body.description,
    )
    _audit_guardrail_change(
        tenant,
        op="create",
        subject=rule.id,
        payload={"rule": rule.to_dict()},
    )
    return {"ok": True, "item": rule.to_dict()}


@router.put("/guardrails/rules/{rule_id}")
async def put_guardrail_rule(
    rule_id: str,
    body: RulePatch,
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    try:
        updated = update_rule(rule_id, body.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "GRD_404", "message": "not_found"},
        ) from exc
    except ValueError as exc:
        if str(exc) == "builtin_rule_readonly":
            raise HTTPException(
                status_code=403,
                detail={"code": "GRD_403", "message": "builtin_readonly"},
            ) from exc
        raise
    _audit_guardrail_change(
        tenant,
        op="update",
        subject=rule_id,
        payload={"rule": updated.to_dict()},
    )
    return {"ok": True, "item": updated.to_dict()}


@router.delete("/guardrails/rules/{rule_id}")
async def remove_guardrail_rule(
    rule_id: str,
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    try:
        ok = delete_rule(rule_id)
    except ValueError as exc:
        if str(exc) == "builtin_rule_readonly":
            raise HTTPException(
                status_code=403,
                detail={"code": "GRD_403", "message": "builtin_readonly"},
            ) from exc
        raise
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"code": "GRD_404", "message": "not_found"},
        )
    _audit_guardrail_change(tenant, op="delete", subject=rule_id, payload={})
    return {"ok": True, "id": rule_id}


@router.get("/guardrails/risk-matrix")
async def get_guardrails_risk_matrix(
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    matrix = get_risk_matrix()
    return {
        "levels": list(RISK_LEVELS),
        "matrix": matrix,
        "actions": ["allow", "require_approval", "deny"],
    }


@router.put("/guardrails/risk-matrix")
async def put_guardrails_risk_matrix(
    body: RiskMatrixPatch,
    tenant: TenantContext = Depends(require_console_super_admin),
) -> dict[str, Any]:
    matrix = update_risk_matrix(body.matrix)
    _audit_guardrail_change(
        tenant,
        op="risk_matrix_update",
        subject="risk_matrix",
        payload={"matrix": matrix},
    )
    return {"ok": True, "matrix": matrix}


@router.post("/guardrails/dry-run")
async def post_guardrails_dry_run(
    body: DryRunRequest,
    tenant: TenantContext = Depends(require_console_reader),
) -> dict[str, Any]:
    if tenant.role != "super_admin" and not tenant.has_permission("admin:*"):
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_002", "message": "super_admin_required"},
        )
    result = await dry_run(
        side=body.side,
        text=body.text,
        risk_level=body.risk_level,
    )
    return {"ok": True, **result}
