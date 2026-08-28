"""Org domain constants / DTOs (Wave B). SQLAlchemy ORM lives on pgvector Base."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

BUSINESS_ROLES_V1 = frozenset({"member", "dept_manager"})


@dataclass(frozen=True)
class OrgUnitDTO:
    id: str
    tenant_id: str
    parent_id: str | None
    name: str
    path: str
    deleted_at: datetime | None
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "path": self.path,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass(frozen=True)
class OrgMembershipDTO:
    id: str
    tenant_id: str
    user_id: str
    org_unit_id: str
    is_primary: bool
    business_roles: list[str]
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "org_unit_id": self.org_unit_id,
            "is_primary": self.is_primary,
            "business_roles": list(self.business_roles),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def normalize_business_roles(roles: list[str] | None) -> list[str]:
    """Keep only known v1 roles; unknown ignored (no elevation)."""
    out: list[str] = []
    for r in roles or []:
        if r in BUSINESS_ROLES_V1 and r not in out:
            out.append(r)
    if not out:
        out = ["member"]
    return out
