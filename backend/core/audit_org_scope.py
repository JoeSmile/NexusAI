"""Audit query visibility via OrgScope (Wave B4)."""

from __future__ import annotations

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from packages.auth.models import TenantContext
from backend.core.org.scope import resolve_org_scope


def audit_user_filter(
    session: Session, tenant: TenantContext
) -> tuple[str | None, dict]:
    """
    Return (sql_fragment, params) restricting audit_logs.user_id.

    - tenant_admin / auditor / super_admin: no extra user filter (tenant filter elsewhere)
    - dept_manager: users who have membership in visible units/subtree
    - member / user: only self
    """
    scope = resolve_org_scope(
        session,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        platform_role=tenant.role,
        is_cross_tenant=tenant.is_cross_tenant,
    )
    if scope.sees_full_tenant:
        return None, {}

    if "dept_manager" in scope.business_roles and (
        scope.org_unit_ids or scope.subtree_paths
    ):
        unit_ids = set(scope.org_unit_ids)
        for pfx in scope.subtree_paths:
            rows = session.execute(
                text(
                    "SELECT id FROM org_units "
                    "WHERE tenant_id = :tid AND deleted_at IS NULL "
                    "AND path LIKE :pfx"
                ),
                {"tid": tenant.tenant_id, "pfx": pfx + "%"},
            ).fetchall()
            unit_ids.update(r.id for r in rows)
        if not unit_ids:
            return "user_id = :audit_self", {"audit_self": tenant.user_id}

        oid_list = list(unit_ids)
        stmt = text(
            "SELECT DISTINCT user_id FROM org_memberships "
            "WHERE tenant_id = :tid AND org_unit_id IN :oids"
        ).bindparams(bindparam("oids", expanding=True))
        rows = session.execute(
            stmt, {"tid": tenant.tenant_id, "oids": oid_list}
        ).fetchall()
        uids = [r.user_id for r in rows] or [tenant.user_id]
        if len(uids) == 1:
            return "user_id = :audit_self", {"audit_self": uids[0]}
        params = {f"au{i}": u for i, u in enumerate(uids)}
        placeholders = ", ".join(f":au{i}" for i in range(len(uids)))
        return f"user_id IN ({placeholders})", params

    return "user_id = :audit_self", {"audit_self": tenant.user_id}
