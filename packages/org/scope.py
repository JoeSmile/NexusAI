"""OrgScope facade — unique entry for org visibility / access (Wave B2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from packages.org.service import list_memberships_for_user


@dataclass(frozen=True)
class OrgScope:
    tenant_id: str
    user_id: str
    platform_role: str
    primary_org_unit_id: str | None
    org_unit_ids: frozenset[str]
    subtree_paths: frozenset[str]
    business_roles: frozenset[str]
    is_cross_tenant: bool = False

    @property
    def sees_full_tenant(self) -> bool:
        if self.is_cross_tenant and self.platform_role in (
            "super_admin",
            "auditor",
        ):
            return True
        return self.platform_role in ("tenant_admin", "super_admin", "auditor")


def resolve_org_scope(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
    platform_role: str,
    is_cross_tenant: bool = False,
) -> OrgScope:
    """Realtime resolve — must be used for assert_org_access / approve paths."""
    mems = list_memberships_for_user(
        session, tenant_id=tenant_id, user_id=user_id
    )
    primary = next((m.org_unit_id for m in mems if m.is_primary), None)
    if primary is None and mems:
        primary = mems[0].org_unit_id

    org_ids = frozenset(m.org_unit_id for m in mems)
    roles: set[str] = set()
    for m in mems:
        roles.update(m.business_roles)

    subtree: set[str] = set()
    is_manager = "dept_manager" in roles
    if is_manager and org_ids:
        for oid in org_ids:
            row = session.execute(
                text(
                    "SELECT id, path FROM org_units "
                    "WHERE tenant_id = :tid AND id = :id AND deleted_at IS NULL"
                ),
                {"tid": tenant_id, "id": oid},
            ).fetchone()
            if row:
                p = row.path if row.path.endswith("/") else row.path + "/"
                subtree.add(p)

    return OrgScope(
        tenant_id=tenant_id,
        user_id=user_id,
        platform_role=platform_role,
        primary_org_unit_id=primary,
        org_unit_ids=org_ids,
        subtree_paths=frozenset(subtree),
        business_roles=frozenset(roles),
        is_cross_tenant=is_cross_tenant,
    )


def visible_org_filter(scope: OrgScope) -> dict[str, Any]:
    """Hints for list/tree filtering (not a security substitute for assert)."""
    if scope.sees_full_tenant:
        return {"mode": "tenant", "tenant_id": scope.tenant_id}
    if scope.subtree_paths:
        return {
            "mode": "subtree",
            "unit_ids": set(scope.org_unit_ids),
            "path_prefixes": set(scope.subtree_paths),
        }
    return {
        "mode": "units",
        "unit_ids": set(scope.org_unit_ids),
        "path_prefixes": set(),
    }


def unit_visible(scope: OrgScope, *, unit_id: str, unit_path: str) -> bool:
    if scope.sees_full_tenant:
        return True
    if unit_id in scope.org_unit_ids:
        return True
    path = unit_path if unit_path.endswith("/") else unit_path + "/"
    for pfx in scope.subtree_paths:
        if path.startswith(pfx):
            return True
    return False


def assert_org_access(
    scope: OrgScope,
    resource_org_unit_id: str | None,
    *,
    session: Session | None = None,
    unit_path: str | None = None,
) -> None:
    """Raise 403 if resource org is outside scope. NULL id → deny for non-governance."""
    if scope.sees_full_tenant:
        return
    if not resource_org_unit_id:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ORG_011",
                "message": "org_access_denied",
                "hint": "missing_org_unit_id",
            },
        )
    if resource_org_unit_id in scope.org_unit_ids:
        return

    path = unit_path
    if path is None and session is not None:
        row = session.execute(
            text(
                "SELECT path FROM org_units "
                "WHERE tenant_id = :tid AND id = :id"
            ),
            {"tid": scope.tenant_id, "id": resource_org_unit_id},
        ).fetchone()
        path = row.path if row else None

    if path and scope.subtree_paths:
        p = path if path.endswith("/") else path + "/"
        for pfx in scope.subtree_paths:
            if p.startswith(pfx):
                return

    raise HTTPException(
        status_code=403,
        detail={
            "code": "ORG_011",
            "message": "org_access_denied",
            "hint": "outside_org_scope",
        },
    )
