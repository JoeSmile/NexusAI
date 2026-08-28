"""Organization CRUD API — Wave B1."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.core.org import service as org_svc
from backend.database.pgvector_session import get_pg_session
from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext

router = APIRouter(prefix="/org", tags=["org"])


class CreateUnitBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    parent_id: str | None = None


class MoveUnitBody(BaseModel):
    parent_id: str | None = None


class UpsertMembershipBody(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    org_unit_id: str = Field(..., min_length=1)
    is_primary: bool = False
    business_roles: list[str] = Field(default_factory=lambda: ["member"])


def _tid(tenant: TenantContext) -> str:
    return tenant.tenant_id


@router.post("/units")
async def create_unit(
    body: CreateUnitBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    org_svc.require_org_writer(
        role=tenant.role, is_cross_tenant=tenant.is_cross_tenant
    )
    sf = get_pg_session()
    with sf.Session() as session:
        unit = org_svc.create_unit(
            session,
            tenant_id=_tid(tenant),
            name=body.name,
            parent_id=body.parent_id,
        )
    return unit.to_dict()


@router.patch("/units/{unit_id}/move")
async def move_unit(
    unit_id: str,
    body: MoveUnitBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    org_svc.require_org_writer(
        role=tenant.role, is_cross_tenant=tenant.is_cross_tenant
    )
    sf = get_pg_session()
    with sf.Session() as session:
        unit = org_svc.move_unit(
            session,
            tenant_id=_tid(tenant),
            unit_id=unit_id,
            new_parent_id=body.parent_id,
        )
    return unit.to_dict()


@router.delete("/units/{unit_id}")
async def delete_unit(
    unit_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    org_svc.require_org_writer(
        role=tenant.role, is_cross_tenant=tenant.is_cross_tenant
    )
    sf = get_pg_session()
    with sf.Session() as session:
        return org_svc.delete_unit(
            session, tenant_id=_tid(tenant), unit_id=unit_id
        )


@router.get("/units/tree")
async def get_units_tree(
    include_deleted: bool = Query(False),
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> list[dict[str, Any]]:
    if include_deleted and tenant.role not in (
        "tenant_admin",
        "super_admin",
    ):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail={
                "code": "ORG_010",
                "message": "include_deleted_admin_only",
            },
        )

    from backend.core.org.scope import resolve_org_scope, visible_org_filter

    sf = get_pg_session()
    with sf.Session() as session:
        scope = resolve_org_scope(
            session,
            tenant_id=_tid(tenant),
            user_id=tenant.user_id,
            platform_role=tenant.role,
            is_cross_tenant=tenant.is_cross_tenant,
        )
        filt = visible_org_filter(scope)
        visible_ids: frozenset[str] | None = None
        visible_pfx: frozenset[str] | None = None
        if filt["mode"] == "tenant":
            pass
        elif filt["mode"] == "subtree":
            visible_ids = frozenset(filt["unit_ids"])
            visible_pfx = frozenset(filt["path_prefixes"])
        else:
            visible_ids = frozenset(filt["unit_ids"])
            visible_pfx = frozenset()

        return org_svc.list_units_tree(
            session,
            tenant_id=_tid(tenant),
            include_deleted=include_deleted,
            visible_unit_ids=visible_ids,
            visible_path_prefixes=visible_pfx,
        )


@router.post("/memberships")
async def upsert_membership(
    body: UpsertMembershipBody,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, Any]:
    org_svc.require_org_writer(
        role=tenant.role, is_cross_tenant=tenant.is_cross_tenant
    )
    sf = get_pg_session()
    with sf.Session() as session:
        m = org_svc.upsert_membership(
            session,
            tenant_id=_tid(tenant),
            user_id=body.user_id.strip(),
            org_unit_id=body.org_unit_id,
            is_primary=body.is_primary,
            business_roles=body.business_roles,
        )
    return m.to_dict()


@router.get("/memberships/me")
async def my_memberships(
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> list[dict[str, Any]]:
    sf = get_pg_session()
    with sf.Session() as session:
        rows = org_svc.list_memberships_for_user(
            session, tenant_id=_tid(tenant), user_id=tenant.user_id
        )
    return [r.to_dict() for r in rows]


@router.get("/units/{unit_id}/memberships")
async def unit_memberships(
    unit_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> list[dict[str, Any]]:
    from backend.core.org.scope import assert_org_access, resolve_org_scope

    sf = get_pg_session()
    with sf.Session() as session:
        unit = org_svc.get_unit(session, tenant_id=_tid(tenant), unit_id=unit_id)
        if unit is None:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=404,
                detail={"code": "ORG_004", "message": "unit_not_found"},
            )
        scope = resolve_org_scope(
            session,
            tenant_id=_tid(tenant),
            user_id=tenant.user_id,
            platform_role=tenant.role,
            is_cross_tenant=tenant.is_cross_tenant,
        )
        assert_org_access(
            scope, unit_id, session=session, unit_path=unit.path
        )
        rows = org_svc.list_memberships_for_unit(
            session, tenant_id=_tid(tenant), org_unit_id=unit_id
        )
    return [r.to_dict() for r in rows]


@router.delete("/memberships/{membership_id}")
async def delete_membership(
    membership_id: str,
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> dict[str, str]:
    org_svc.require_org_writer(
        role=tenant.role, is_cross_tenant=tenant.is_cross_tenant
    )
    sf = get_pg_session()
    with sf.Session() as session:
        org_svc.delete_membership(
            session, tenant_id=_tid(tenant), membership_id=membership_id
        )
    return {"status": "deleted", "id": membership_id}
