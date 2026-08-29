"""Admin console skill_assets routes (Task 67 slice 3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from packages.skill_assets.builtin_catalog import BUILTIN_SKILL_ASSET_CATALOG
from packages.skill_assets.service import (
    deprecate,
    evolution_stats,
    get_skill_asset,
    list_skill_assets,
    publish,
    reject_draft,
)
from packages.database.pgvector_session import SkillAsset
from packages.auth.models import TenantContext
from packages.capability.console_access import (
    is_console_super_admin,
    require_console_reader,
)

router = APIRouter()

_DOMAIN_BY_NAME = {entry["name"]: entry["skill_id"] for entry in BUILTIN_SKILL_ASSET_CATALOG}


def _skill_domain(name: str) -> str:
    if name in _DOMAIN_BY_NAME:
        return str(_DOMAIN_BY_NAME[name])
    if "_" in name:
        return name.split("_", 1)[0]
    return "custom"


def _skill_source(row: SkillAsset) -> str:
    desc = str(row.description or "")
    if "mined_from" in desc:
        return "mined"
    if row.name in _DOMAIN_BY_NAME:
        return "builtin"
    return "manual"


def _usage_view(stats: dict[str, Any] | None) -> dict[str, Any]:
    body = dict(stats or {})
    uses = int(body.get("uses") or 0)
    successes = int(body.get("successes") or 0)
    return {
        "uses": uses,
        "successes": successes,
        "avg_tokens": float(body.get("avg_tokens") or 0.0),
        "hit_rate": round(successes / uses, 4) if uses else 0.0,
        "required_permissions": list(body.get("required_permissions") or []),
    }


def _summary(row: SkillAsset) -> dict[str, Any]:
    usage = _usage_view(row.usage_stats if isinstance(row.usage_stats, dict) else {})
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "domain": _skill_domain(row.name),
        "status": row.status,
        "version": row.version,
        "visibility": row.visibility,
        "description": (row.description or "")[:240],
        "source": _skill_source(row),
        "usage": usage,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _detail(row: SkillAsset) -> dict[str, Any]:
    return {
        **_summary(row),
        "owner_user_id": row.owner_user_id,
        "cot_template": row.cot_template,
        "ir_skeleton": dict(row.ir_skeleton or {}),
    }


def _tenant_scope(tenant: TenantContext) -> str | None:
    return None if is_console_super_admin(tenant) else tenant.tenant_id


def _resolve_asset(tenant: TenantContext, asset_id: str) -> SkillAsset:
    if is_console_super_admin(tenant):
        rows = list_skill_assets(limit=500)
        for row in rows:
            if row.id == asset_id:
                return row
        raise HTTPException(
            status_code=404,
            detail={"code": "SKA_404", "message": "not_found"},
        )
    row = get_skill_asset(tenant_id=tenant.tenant_id, asset_id=asset_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "SKA_404", "message": "not_found"},
        )
    return row


@router.get("/skills/evolution")
async def get_skills_evolution(
    tenant: TenantContext = Depends(require_console_reader),
) -> dict[str, Any]:
    return evolution_stats(tenant_id=_tenant_scope(tenant))


@router.get("/skills")
async def list_skills(
    tenant: TenantContext = Depends(require_console_reader),
    q: str | None = Query(None),
    status: str | None = Query(None),
    domain: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    rows = list_skill_assets(
        tenant_id=_tenant_scope(tenant),
        status=status,
        q=q,
        limit=limit,
    )
    items = [_summary(r) for r in rows]
    if domain:
        needle = domain.strip().lower()
        items = [i for i in items if i["domain"].lower() == needle]
    return {"items": items, "total": len(items)}


@router.get("/skills/{asset_id}")
async def get_skill_detail(
    asset_id: str,
    tenant: TenantContext = Depends(require_console_reader),
) -> dict[str, Any]:
    row = _resolve_asset(tenant, asset_id)
    return _detail(row)


@router.post("/skills/{asset_id}/publish")
async def publish_skill(
    asset_id: str,
    tenant: TenantContext = Depends(require_console_reader),
) -> dict[str, Any]:
    row = _resolve_asset(tenant, asset_id)
    published = publish(
        tenant_id=row.tenant_id,
        asset_id=asset_id,
        actor_user_id=tenant.user_id or "admin",
    )
    return {"ok": True, "item": _detail(published)}


@router.post("/skills/{asset_id}/deprecate")
async def deprecate_skill(
    asset_id: str,
    tenant: TenantContext = Depends(require_console_reader),
) -> dict[str, Any]:
    row = _resolve_asset(tenant, asset_id)
    updated = deprecate(tenant_id=row.tenant_id, asset_id=asset_id)
    return {"ok": True, "item": _detail(updated)}


@router.post("/skills/{asset_id}/reject")
async def reject_skill_draft(
    asset_id: str,
    tenant: TenantContext = Depends(require_console_reader),
) -> dict[str, Any]:
    row = _resolve_asset(tenant, asset_id)
    if row.status != "draft":
        raise HTTPException(
            status_code=409,
            detail={"code": "SKA_409", "message": "not_draft"},
        )
    ok = reject_draft(tenant_id=row.tenant_id, asset_id=asset_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"code": "SKA_404", "message": "not_found"},
        )
    return {"ok": True, "id": asset_id}
