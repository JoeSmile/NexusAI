"""Map skill_asset WorkflowIR skeletons onto published workflows (Task 86)."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from packages.auth.models import TenantContext
from packages.database.pgvector_session import SkillAsset, Workflow


def is_workflow_ir_skeleton(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get("nodes"), list)


def workflow_id_for_asset(asset_id: str) -> str:
    digest = hashlib.sha256(f"skill_asset:{asset_id}".encode()).hexdigest()
    return (
        f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-"
        f"{digest[16:20]}-{digest[20:32]}"
    )


def sync_skill_workflow_on_publish(
    session: Session,
    *,
    asset: SkillAsset,
    created_by: str,
) -> str | None:
    """Create a published workflow when skeleton is engine-legal WorkflowIR.

    v1 只建不更：同一 asset 只能 publish 一次（CAS draft→published），
    已存在的 workflow 行不改 IR。``{steps: ...}`` 模板骨架返回 None。
    Invalid WorkflowIR raises HTTPException from validate_ir_for_save.
    """
    skel = asset.ir_skeleton if isinstance(asset.ir_skeleton, dict) else {}
    if not is_workflow_ir_skeleton(skel):
        return None

    from packages.workflow.service import validate_ir_for_save

    tenant = TenantContext(
        tenant_id=asset.tenant_id,
        user_id=created_by or asset.owner_user_id or "system",
        role="tenant_admin",
        extra_permissions=["*"],
        is_cross_tenant=False,
    )
    ir = validate_ir_for_save(dict(skel), tenant)
    wid = workflow_id_for_asset(str(asset.id))
    now = datetime.utcnow()
    dump = ir.model_dump()
    row = (
        session.query(Workflow)
        .filter(Workflow.tenant_id == asset.tenant_id, Workflow.id == wid)
        .one_or_none()
    )
    name = str(asset.name or "skill")[:255]
    if row is None:
        row = Workflow(
            id=wid,
            tenant_id=asset.tenant_id,
            org_unit_id=None,
            name=name,
            status="published",
            ir_json=dump,
            version="V1.0.0",
            revision=1,
            forked_from_id=None,
            created_by=created_by or "system",
            intent_tags=[],
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        # v1: publish is once; do not mutate an existing workflow row.
        return wid
    session.flush()
    return wid


def archive_skill_workflow(
    session: Session,
    *,
    tenant_id: str,
    asset_id: str,
) -> None:
    wid = workflow_id_for_asset(asset_id)
    row = (
        session.query(Workflow)
        .filter(Workflow.tenant_id == tenant_id, Workflow.id == wid)
        .one_or_none()
    )
    if row is None:
        return
    if row.status == "published":
        row.status = "archived"
        row.updated_at = datetime.utcnow()
        session.flush()
