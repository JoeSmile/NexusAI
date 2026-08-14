"""Org units + memberships service (Wave B1)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.org.models import (
    OrgMembershipDTO,
    OrgUnitDTO,
    normalize_business_roles,
)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _new_id() -> str:
    return str(uuid.uuid4())


def _row_unit(row: Any) -> OrgUnitDTO:
    return OrgUnitDTO(
        id=row.id,
        tenant_id=row.tenant_id,
        parent_id=row.parent_id,
        name=row.name,
        path=row.path,
        deleted_at=row.deleted_at,
        created_at=row.created_at,
    )


def _row_membership(row: Any) -> OrgMembershipDTO:
    roles = row.business_roles
    if isinstance(roles, str):
        roles = json.loads(roles)
    return OrgMembershipDTO(
        id=row.id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        org_unit_id=row.org_unit_id,
        is_primary=bool(row.is_primary),
        business_roles=list(roles or []),
        created_at=row.created_at,
    )


def can_write_org(role: str, *, is_cross_tenant: bool) -> bool:
    if is_cross_tenant and role in ("super_admin", "auditor"):
        # auditor is read-only for org writes
        return role == "super_admin"
    return role in ("tenant_admin", "super_admin")


def require_org_writer(*, role: str, is_cross_tenant: bool) -> None:
    if not can_write_org(role, is_cross_tenant=is_cross_tenant):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ORG_001",
                "message": "org_write_denied",
                "hint": "tenant_admin_or_super_admin_required",
            },
        )


def compute_child_path(parent_path: str | None, unit_id: str) -> str:
    if not parent_path:
        return f"/{unit_id}/"
    if not parent_path.endswith("/"):
        parent_path = parent_path + "/"
    return f"{parent_path}{unit_id}/"


def rewrite_subtree_paths(
    *,
    old_path: str,
    new_path: str,
    descendant_paths: list[str],
) -> list[tuple[str, str]]:
    """Return (old, new) path pairs for unit + descendants (prefix rewrite)."""
    if not old_path.endswith("/"):
        old_path = old_path + "/"
    if not new_path.endswith("/"):
        new_path = new_path + "/"
    out: list[tuple[str, str]] = [(old_path, new_path)]
    for p in descendant_paths:
        if p == old_path:
            continue
        if p.startswith(old_path):
            out.append((p, new_path + p[len(old_path) :]))
    return out


def _table_exists(session: Session, name: str) -> bool:
    row = session.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :n LIMIT 1"
        ),
        {"n": name},
    ).fetchone()
    return row is not None


def _count_members(session: Session, *, tenant_id: str, org_unit_id: str) -> int:
    row = session.execute(
        text(
            "SELECT COUNT(*) AS c FROM org_memberships "
            "WHERE tenant_id = :tid AND org_unit_id = :oid"
        ),
        {"tid": tenant_id, "oid": org_unit_id},
    ).fetchone()
    return int(row.c if row else 0)


def _has_workflow_deps(session: Session, *, tenant_id: str, org_unit_id: str) -> bool:
    """Probe published WF / in-flight runs if tables exist; else False."""
    # Tables not in Wave B — probe only; do not invent schema.
    for table, col_hint in (
        ("workflow_definitions", "org_unit_id"),
        ("workflows", "org_unit_id"),
        ("workflow_runs", "org_unit_id"),
        ("runs", "org_unit_id"),
    ):
        if not _table_exists(session, table):
            continue
        # Column may not exist yet — skip safely
        col = session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t AND column_name=:c LIMIT 1"
            ),
            {"t": table, "c": col_hint},
        ).fetchone()
        if not col:
            continue
        row = session.execute(
            text(
                f"SELECT 1 FROM {table} WHERE tenant_id = :tid AND {col_hint} = :oid LIMIT 1"
            ),
            {"tid": tenant_id, "oid": org_unit_id},
        ).fetchone()
        if row:
            return True
    return False


def get_unit(
    session: Session,
    *,
    tenant_id: str,
    unit_id: str,
    include_deleted: bool = False,
) -> OrgUnitDTO | None:
    sql = (
        "SELECT id, tenant_id, parent_id, name, path, deleted_at, created_at "
        "FROM org_units WHERE tenant_id = :tid AND id = :id"
    )
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    row = session.execute(text(sql), {"tid": tenant_id, "id": unit_id}).fetchone()
    return _row_unit(row) if row else None


def create_unit(
    session: Session,
    *,
    tenant_id: str,
    name: str,
    parent_id: str | None,
) -> OrgUnitDTO:
    parent: OrgUnitDTO | None = None
    if parent_id:
        parent = get_unit(session, tenant_id=tenant_id, unit_id=parent_id)
        if parent is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "ORG_002", "message": "parent_not_found"},
            )
        if parent.deleted_at is not None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "ORG_003",
                    "message": "parent_archived",
                    "hint": "cannot_attach_to_soft_deleted_unit",
                },
            )

    unit_id = _new_id()
    path = compute_child_path(parent.path if parent else None, unit_id)
    now = _utcnow()
    session.execute(
        text(
            "INSERT INTO org_units "
            "(id, tenant_id, parent_id, name, path, deleted_at, created_at) "
            "VALUES (:id, :tid, :pid, :name, :path, NULL, :created)"
        ),
        {
            "id": unit_id,
            "tid": tenant_id,
            "pid": parent_id,
            "name": name.strip(),
            "path": path,
            "created": now,
        },
    )
    session.commit()
    return OrgUnitDTO(
        id=unit_id,
        tenant_id=tenant_id,
        parent_id=parent_id,
        name=name.strip(),
        path=path,
        deleted_at=None,
        created_at=now,
    )


def move_unit(
    session: Session,
    *,
    tenant_id: str,
    unit_id: str,
    new_parent_id: str | None,
) -> OrgUnitDTO:
    unit = get_unit(session, tenant_id=tenant_id, unit_id=unit_id)
    if unit is None:
        raise HTTPException(
            status_code=404, detail={"code": "ORG_004", "message": "unit_not_found"}
        )
    if new_parent_id == unit_id:
        raise HTTPException(
            status_code=400, detail={"code": "ORG_005", "message": "cannot_parent_self"}
        )

    new_parent: OrgUnitDTO | None = None
    if new_parent_id:
        new_parent = get_unit(session, tenant_id=tenant_id, unit_id=new_parent_id)
        if new_parent is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "ORG_002", "message": "parent_not_found"},
            )
        if new_parent.deleted_at is not None:
            raise HTTPException(
                status_code=400,
                detail={"code": "ORG_003", "message": "parent_archived"},
            )
        if new_parent.path.startswith(unit.path):
            raise HTTPException(
                status_code=400,
                detail={"code": "ORG_006", "message": "cannot_move_under_descendant"},
            )

    old_path = unit.path if unit.path.endswith("/") else unit.path + "/"
    new_path = compute_child_path(new_parent.path if new_parent else None, unit_id)

    rows = session.execute(
        text(
            "SELECT id, path FROM org_units "
            "WHERE tenant_id = :tid AND (id = :id OR path LIKE :pfx)"
        ),
        {"tid": tenant_id, "id": unit_id, "pfx": old_path + "%"},
    ).fetchall()

    for r in rows:
        if r.id == unit_id:
            np = new_path
        else:
            np = new_path + r.path[len(old_path) :]
        session.execute(
            text("UPDATE org_units SET path = :np WHERE tenant_id = :tid AND id = :rid"),
            {"tid": tenant_id, "rid": r.id, "np": np},
        )
    session.execute(
        text(
            "UPDATE org_units SET parent_id = :pid "
            "WHERE tenant_id = :tid AND id = :id"
        ),
        {"tid": tenant_id, "id": unit_id, "pid": new_parent_id},
    )
    session.commit()
    updated = get_unit(session, tenant_id=tenant_id, unit_id=unit_id)
    assert updated is not None
    return updated


def delete_unit(session: Session, *, tenant_id: str, unit_id: str) -> dict[str, Any]:
    unit = get_unit(session, tenant_id=tenant_id, unit_id=unit_id, include_deleted=True)
    if unit is None:
        raise HTTPException(
            status_code=404, detail={"code": "ORG_004", "message": "unit_not_found"}
        )
    if unit.deleted_at is not None:
        return {"status": "already_archived", "id": unit_id, "mode": "soft"}

    has_members = _count_members(session, tenant_id=tenant_id, org_unit_id=unit_id) > 0
    has_wf = _has_workflow_deps(session, tenant_id=tenant_id, org_unit_id=unit_id)

    if has_members or has_wf:
        now = _utcnow()
        session.execute(
            text(
                "UPDATE org_units SET deleted_at = :ts "
                "WHERE tenant_id = :tid AND id = :id"
            ),
            {"tid": tenant_id, "id": unit_id, "ts": now},
        )
        session.commit()
        return {
            "status": "archived",
            "id": unit_id,
            "mode": "soft",
            "reason": "has_dependencies",
        }

    # No deps → hard delete (leaf assumed; children would be deps via members or structure)
    child = session.execute(
        text(
            "SELECT 1 FROM org_units WHERE tenant_id = :tid AND parent_id = :id "
            "AND deleted_at IS NULL LIMIT 1"
        ),
        {"tid": tenant_id, "id": unit_id},
    ).fetchone()
    if child:
        now = _utcnow()
        session.execute(
            text(
                "UPDATE org_units SET deleted_at = :ts "
                "WHERE tenant_id = :tid AND id = :id"
            ),
            {"tid": tenant_id, "id": unit_id, "ts": now},
        )
        session.commit()
        return {
            "status": "archived",
            "id": unit_id,
            "mode": "soft",
            "reason": "has_children",
        }

    session.execute(
        text("DELETE FROM org_units WHERE tenant_id = :tid AND id = :id"),
        {"tid": tenant_id, "id": unit_id},
    )
    session.commit()
    return {"status": "deleted", "id": unit_id, "mode": "hard"}


def list_units_tree(
    session: Session,
    *,
    tenant_id: str,
    include_deleted: bool = False,
    visible_unit_ids: frozenset[str] | None = None,
    visible_path_prefixes: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Flat list of units (client builds tree). Optional OrgScope filters."""
    sql = (
        "SELECT id, tenant_id, parent_id, name, path, deleted_at, created_at "
        "FROM org_units WHERE tenant_id = :tid"
    )
    if not include_deleted:
        sql += " AND deleted_at IS NULL"
    sql += " ORDER BY path"
    rows = session.execute(text(sql), {"tid": tenant_id}).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        u = _row_unit(row)
        if visible_unit_ids is not None or visible_path_prefixes is not None:
            ok = False
            if visible_unit_ids is not None and u.id in visible_unit_ids:
                ok = True
            if visible_path_prefixes is not None:
                for pfx in visible_path_prefixes:
                    if u.path.startswith(pfx):
                        ok = True
                        break
            if not ok:
                continue
        out.append(u.to_dict())
    return out


def upsert_membership(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
    org_unit_id: str,
    is_primary: bool,
    business_roles: list[str] | None,
) -> OrgMembershipDTO:
    unit = get_unit(session, tenant_id=tenant_id, unit_id=org_unit_id)
    if unit is None:
        raise HTTPException(
            status_code=404, detail={"code": "ORG_004", "message": "unit_not_found"}
        )
    if unit.deleted_at is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "ORG_003",
                "message": "unit_archived",
                "hint": "cannot_attach_to_soft_deleted_unit",
            },
        )

    roles = normalize_business_roles(business_roles)
    existing = session.execute(
        text(
            "SELECT id, tenant_id, user_id, org_unit_id, is_primary, business_roles, created_at "
            "FROM org_memberships "
            "WHERE tenant_id = :tid AND user_id = :uid AND org_unit_id = :oid"
        ),
        {"tid": tenant_id, "uid": user_id, "oid": org_unit_id},
    ).fetchone()

    now = _utcnow()
    if is_primary:
        session.execute(
            text(
                "UPDATE org_memberships SET is_primary = false "
                "WHERE tenant_id = :tid AND user_id = :uid AND is_primary = true"
            ),
            {"tid": tenant_id, "uid": user_id},
        )

    if existing:
        session.execute(
            text(
                "UPDATE org_memberships SET is_primary = :pri, business_roles = CAST(:roles AS json) "
                "WHERE id = :id"
            ),
            {"id": existing.id, "pri": is_primary, "roles": json.dumps(roles)},
        )
        session.commit()
        row = session.execute(
            text(
                "SELECT id, tenant_id, user_id, org_unit_id, is_primary, business_roles, created_at "
                "FROM org_memberships WHERE id = :id"
            ),
            {"id": existing.id},
        ).fetchone()
        assert row is not None
        return _row_membership(row)

    mid = _new_id()
    session.execute(
        text(
            "INSERT INTO org_memberships "
            "(id, tenant_id, user_id, org_unit_id, is_primary, business_roles, created_at) "
            "VALUES (:id, :tid, :uid, :oid, :pri, CAST(:roles AS json), :created)"
        ),
        {
            "id": mid,
            "tid": tenant_id,
            "uid": user_id,
            "oid": org_unit_id,
            "pri": is_primary,
            "roles": json.dumps(roles),
            "created": now,
        },
    )
    session.commit()
    return OrgMembershipDTO(
        id=mid,
        tenant_id=tenant_id,
        user_id=user_id,
        org_unit_id=org_unit_id,
        is_primary=is_primary,
        business_roles=roles,
        created_at=now,
    )


def list_memberships_for_user(
    session: Session, *, tenant_id: str, user_id: str
) -> list[OrgMembershipDTO]:
    rows = session.execute(
        text(
            "SELECT id, tenant_id, user_id, org_unit_id, is_primary, business_roles, created_at "
            "FROM org_memberships WHERE tenant_id = :tid AND user_id = :uid "
            "ORDER BY is_primary DESC, created_at"
        ),
        {"tid": tenant_id, "uid": user_id},
    ).fetchall()
    return [_row_membership(r) for r in rows]


def list_memberships_for_unit(
    session: Session, *, tenant_id: str, org_unit_id: str
) -> list[OrgMembershipDTO]:
    rows = session.execute(
        text(
            "SELECT id, tenant_id, user_id, org_unit_id, is_primary, business_roles, created_at "
            "FROM org_memberships WHERE tenant_id = :tid AND org_unit_id = :oid "
            "ORDER BY created_at"
        ),
        {"tid": tenant_id, "oid": org_unit_id},
    ).fetchall()
    return [_row_membership(r) for r in rows]


def delete_membership(session: Session, *, tenant_id: str, membership_id: str) -> None:
    row = session.execute(
        text(
            "SELECT id, tenant_id, user_id, org_unit_id, is_primary, business_roles, created_at "
            "FROM org_memberships WHERE tenant_id = :tid AND id = :id"
        ),
        {"tid": tenant_id, "id": membership_id},
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ORG_007", "message": "membership_not_found"},
        )
    m = _row_membership(row)
    if m.is_primary:
        others = session.execute(
            text(
                "SELECT COUNT(*) AS c FROM org_memberships "
                "WHERE tenant_id = :tid AND user_id = :uid AND id <> :id"
            ),
            {"tid": tenant_id, "uid": m.user_id, "id": membership_id},
        ).fetchone()
        if not others or int(others.c) == 0:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "ORG_008",
                    "message": "cannot_delete_sole_primary",
                    "hint": "assign_another_primary_first",
                },
            )
        raise HTTPException(
            status_code=400,
            detail={
                "code": "ORG_009",
                "message": "cannot_delete_primary",
                "hint": "switch_primary_then_delete",
            },
        )
    session.execute(
        text("DELETE FROM org_memberships WHERE tenant_id = :tid AND id = :id"),
        {"tid": tenant_id, "id": membership_id},
    )
    session.commit()
