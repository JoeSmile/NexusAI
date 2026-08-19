"""Ensure per-tenant builtin content workflows (Task 45b slice 2)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.database.pgvector_session import Workflow

BUILTIN_HOTSPOT_NAME = "内置·抓取相关热点"
HOTSPOT_INTENT_TAGS = ["hotspot", "抓热点", "热点", "hotspot.dig", "挖热点"]

_HOTSPOT_IR: dict[str, Any] = {
    "ir_schema": "1",
    "nodes": [
        {
            "node_id": "dig",
            "kind": "capability",
            "capability_id": "hotspot.dig",
            "name": "抓取相关热点",
        }
    ],
    "edges": [],
}


def _builtin_hotspot_id(tenant_id: str) -> str:
    digest = hashlib.sha256(f"builtin:hotspot.dig:{tenant_id}".encode()).hexdigest()
    # UUID-shaped 32 hex → 8-4-4-4-12
    return (
        f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-"
        f"{digest[16:20]}-{digest[20:32]}"
    )


def ensure_builtin_hotspot_workflow(
    session: Session,
    *,
    tenant_id: str,
    created_by: str = "system",
) -> str:
    """Idempotent: published one-node hotspot.dig workflow with intent_tags."""
    wid = _builtin_hotspot_id(tenant_id)
    row = (
        session.query(Workflow)
        .filter(Workflow.tenant_id == tenant_id, Workflow.id == wid)
        .one_or_none()
    )
    now = datetime.utcnow()
    if row is None:
        row = (
            session.query(Workflow)
            .filter(
                Workflow.tenant_id == tenant_id,
                Workflow.name == BUILTIN_HOTSPOT_NAME,
            )
            .one_or_none()
        )
    if row is None:
        row = Workflow(
            id=wid,
            tenant_id=tenant_id,
            org_unit_id=None,
            name=BUILTIN_HOTSPOT_NAME,
            status="published",
            ir_json=dict(_HOTSPOT_IR),
            version="V1.0.0",
            revision=1,
            forked_from_id=None,
            created_by=created_by or "system",
            intent_tags=list(HOTSPOT_INTENT_TAGS),
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return row.id

    changed = False
    if row.status != "published":
        row.status = "published"
        changed = True
    tags = list(getattr(row, "intent_tags", None) or [])
    if not tags:
        row.intent_tags = list(HOTSPOT_INTENT_TAGS)
        changed = True
    ir = dict(row.ir_json or {})
    if not (ir.get("nodes") or []):
        row.ir_json = dict(_HOTSPOT_IR)
        changed = True
    if changed:
        row.updated_at = now
        session.flush()
    return row.id
