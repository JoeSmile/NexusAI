"""Workflow domain DTOs / constants (Wave C2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

WorkflowStatus = Literal["draft", "published", "archived"]


class WorkflowCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    org_unit_id: str | None = None
    ir: dict[str, Any] | None = None


class WorkflowPatchBody(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    ir: dict[str, Any] | None = None
    base_revision: int = Field(..., ge=0)
    org_unit_id: str | None = None


def workflow_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "org_unit_id": row.org_unit_id,
        "name": row.name,
        "status": row.status,
        "ir": dict(row.ir_json or {}),
        "version": row.version,
        "revision": int(row.revision),
        "forked_from_id": row.forked_from_id,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
