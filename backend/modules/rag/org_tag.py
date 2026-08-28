"""RAG org tagging helpers (Wave B3)."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from packages.auth.models import TenantContext
from backend.core.org.scope import OrgScope, resolve_org_scope, unit_visible


def require_primary_org_for_ingest(
    session: Session, tenant: TenantContext
) -> tuple[str, OrgScope]:
    """Bind ingest to caller's primary org; 400 if missing; 400 if unit archived."""
    scope = resolve_org_scope(
        session,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        platform_role=tenant.role,
        is_cross_tenant=tenant.is_cross_tenant,
    )
    oid = scope.primary_org_unit_id
    if not oid:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "RAG_ORG_001",
                "message": "primary_org_required",
                "hint": "assign_primary_department_before_upload",
            },
        )
    from backend.core.org.service import get_unit

    unit = get_unit(session, tenant_id=tenant.tenant_id, unit_id=oid)
    if unit is None or unit.deleted_at is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "RAG_ORG_002",
                "message": "primary_org_archived_or_missing",
            },
        )
    return oid, scope


def chunk_visible_to_scope(
    scope: OrgScope,
    *,
    org_unit_id: str | None,
    unit_path: str | None = None,
) -> bool:
    """NULL org_unit_id visible only to governance roles."""
    if org_unit_id is None:
        return scope.sees_full_tenant
    if scope.sees_full_tenant:
        return True
    if org_unit_id in scope.org_unit_ids:
        return True
    if unit_path and scope.subtree_paths:
        return unit_visible(scope, unit_id=org_unit_id, unit_path=unit_path)
    # Without path, managers still see own units only unless path provided
    return False
