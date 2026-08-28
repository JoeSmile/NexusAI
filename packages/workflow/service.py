"""Workflow CRUD service (Wave C2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.core.org.scope import OrgScope, assert_org_access, visible_org_filter
from backend.database.pgvector_session import Workflow
from packages.auth.models import TenantContext
from packages.capability.models import CapabilitySpec, CapabilityStatus
from packages.capability.registry import get_capability_registry
from packages.workflow.ir import WorkflowIR, validate_ir_capabilities
from packages.workflow.models import workflow_to_dict


def require_workflow_creator(tenant: TenantContext) -> None:
    if tenant.role in ("tenant_admin", "super_admin"):
        return
    if tenant.is_cross_tenant and tenant.role == "super_admin":
        return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "WF_001",
            "message": "workflow_create_forbidden",
            "hint": "tenant_admin_required",
        },
    )


def require_workflow_editor(tenant: TenantContext, *, created_by: str) -> None:
    if tenant.role in ("tenant_admin", "super_admin"):
        return
    if tenant.user_id == created_by:
        return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "WF_002",
            "message": "workflow_edit_forbidden",
            "hint": "creator_or_tenant_admin_required",
        },
    )


def capability_catalog_visible(spec: CapabilitySpec, tenant: TenantContext) -> bool:
    """租户目录可见性（不含可调 permission）— 保存路径专用。"""
    if spec.status != CapabilityStatus.ENABLED:
        return False
    if spec.tenant_id not in ("*", "", tenant.tenant_id):
        return bool(tenant.is_cross_tenant)
    return True


def validate_ir_for_save(ir_data: dict[str, Any], tenant: TenantContext) -> WorkflowIR:
    try:
        ir = WorkflowIR.model_validate(ir_data)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "WF_010", "message": "invalid_ir", "hint": str(exc)},
        ) from exc

    reg = get_capability_registry()

    def exists(cid: str) -> bool:
        spec = reg.get(cid)
        return spec is not None and capability_catalog_visible(spec, tenant)

    def param_spec(cid: str) -> dict[str, Any] | None:
        spec = reg.get(cid)
        return dict(spec.param_spec) if spec and spec.param_spec else None

    try:
        validate_ir_capabilities(
            ir, get_param_spec=param_spec, capability_exists=exists
        )
    except ValueError as exc:
        msg = str(exc)
        code = "WF_012" if "unknown capability" in msg else "WF_011"
        raise HTTPException(
            status_code=400,
            detail={"code": code, "message": "ir_validation_failed", "hint": msg},
        ) from exc
    return ir


def _get_row(session: Session, *, tenant_id: str, workflow_id: str) -> Workflow:
    row = (
        session.query(Workflow)
        .filter(Workflow.tenant_id == tenant_id, Workflow.id == workflow_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "WF_404", "message": "workflow_not_found"},
        )
    return row


def create_workflow(
    session: Session,
    *,
    tenant: TenantContext,
    org_scope: OrgScope,
    name: str,
    org_unit_id: str | None,
    ir_data: dict[str, Any] | None,
) -> dict[str, Any]:
    require_workflow_creator(tenant)
    # 默认绑主部门；tenant_admin 可显式指定；允许 NULL 全局
    bound = org_unit_id
    if bound is None:
        bound = org_scope.primary_org_unit_id
    if org_unit_id is not None:
        assert_org_access(org_scope, org_unit_id, session=session)

    ir_data = ir_data or {"ir_schema": "1", "nodes": [], "edges": []}
    ir = validate_ir_for_save(ir_data, tenant)

    row = Workflow(
        id=str(uuid.uuid4()),
        tenant_id=tenant.tenant_id,
        org_unit_id=bound,
        name=name,
        status="draft",
        ir_json=ir.model_dump(),
        version="V1.0.0",
        revision=0,
        forked_from_id=None,
        created_by=tenant.user_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return workflow_to_dict(row)


def get_workflow(
    session: Session,
    *,
    tenant: TenantContext,
    org_scope: OrgScope,
    workflow_id: str,
) -> dict[str, Any]:
    row = _get_row(session, tenant_id=tenant.tenant_id, workflow_id=workflow_id)
    assert_org_access(org_scope, row.org_unit_id, session=session)
    return workflow_to_dict(row)


def list_workflows(
    session: Session,
    *,
    tenant: TenantContext,
    org_scope: OrgScope,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    q = session.query(Workflow).filter(Workflow.tenant_id == tenant.tenant_id)
    if status:
        q = q.filter(Workflow.status == status)

    filt = visible_org_filter(org_scope)
    if filt["mode"] != "tenant":
        unit_ids = set(filt.get("unit_ids") or set())
        # NULL org = 全局，仅治理角色可见（sees_full_tenant 已覆盖）
        q = q.filter(Workflow.org_unit_id.in_(unit_ids))

    rows = (
        q.order_by(Workflow.updated_at.desc())
        .offset(max(0, offset))
        .limit(min(max(1, limit), 100))
        .all()
    )
    return [workflow_to_dict(r) for r in rows]


def patch_workflow(
    session: Session,
    *,
    tenant: TenantContext,
    org_scope: OrgScope,
    workflow_id: str,
    base_revision: int,
    name: str | None = None,
    ir_data: dict[str, Any] | None = None,
    org_unit_id: str | None = None,
    request_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from packages.workflow.grants import normalize_request_policy

    row = _get_row(session, tenant_id=tenant.tenant_id, workflow_id=workflow_id)
    assert_org_access(org_scope, row.org_unit_id, session=session)
    require_workflow_editor(tenant, created_by=row.created_by)

    if row.status != "draft":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WF_020",
                "message": "not_draft",
                "hint": "fork_draft_then_edit",
            },
        )
    if int(row.revision) != base_revision:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WF_021",
                "message": "revision_conflict",
                "hint": "reload_and_retry",
                "current_revision": int(row.revision),
            },
        )

    if name is not None:
        row.name = name
    if org_unit_id is not None:
        assert_org_access(org_scope, org_unit_id, session=session)
        row.org_unit_id = org_unit_id
    if ir_data is not None:
        ir = validate_ir_for_save(ir_data, tenant)
        row.ir_json = ir.model_dump()
    if request_policy is not None:
        row.request_policy = normalize_request_policy(request_policy)

    row.revision = int(row.revision) + 1
    row.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(row)
    return workflow_to_dict(row)


def publish_workflow(
    session: Session,
    *,
    tenant: TenantContext,
    org_scope: OrgScope,
    workflow_id: str,
    base_revision: int | None = None,
    intent_tags: list[str] | None = None,
) -> dict[str, Any]:
    row = _get_row(session, tenant_id=tenant.tenant_id, workflow_id=workflow_id)
    assert_org_access(org_scope, row.org_unit_id, session=session)
    require_workflow_editor(tenant, created_by=row.created_by)

    if row.status != "draft":
        raise HTTPException(
            status_code=409,
            detail={"code": "WF_030", "message": "already_published_or_archived"},
        )
    if base_revision is not None and int(row.revision) != base_revision:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WF_021",
                "message": "revision_conflict",
                "current_revision": int(row.revision),
            },
        )

    # 再校验一次 IR（防止 registry 变更）
    validate_ir_for_save(dict(row.ir_json or {}), tenant)

    row.status = "published"
    row.revision = int(row.revision) + 1
    if intent_tags:
        # 评审 08-14 I-1:发布时写入 intent_tags,40.86 Chat 桥靠它匹配(桥只读,发布不写则桥不可触发)
        row.intent_tags = [t.strip() for t in intent_tags if t and t.strip()]
    row.updated_at = datetime.utcnow()

    if row.forked_from_id:
        src = (
            session.query(Workflow)
            .filter(
                Workflow.tenant_id == tenant.tenant_id,
                Workflow.id == row.forked_from_id,
            )
            .one_or_none()
        )
        if src is not None and src.status == "published":
            src.status = "archived"
            src.updated_at = datetime.utcnow()

    session.commit()
    session.refresh(row)
    return workflow_to_dict(row)


def fork_draft(
    session: Session,
    *,
    tenant: TenantContext,
    org_scope: OrgScope,
    workflow_id: str,
) -> dict[str, Any]:
    require_workflow_creator(tenant)
    src = _get_row(session, tenant_id=tenant.tenant_id, workflow_id=workflow_id)
    assert_org_access(org_scope, src.org_unit_id, session=session)
    if src.status != "published":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WF_040",
                "message": "fork_requires_published",
            },
        )

    row = Workflow(
        id=str(uuid.uuid4()),
        tenant_id=tenant.tenant_id,
        org_unit_id=src.org_unit_id,
        name=src.name,
        status="draft",
        ir_json=dict(src.ir_json or {}),
        version=src.version,
        revision=0,
        forked_from_id=src.id,
        created_by=tenant.user_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return workflow_to_dict(row)


def delete_workflow(
    session: Session,
    *,
    tenant: TenantContext,
    org_scope: OrgScope,
    workflow_id: str,
) -> dict[str, Any]:
    require_workflow_creator(tenant)
    row = _get_row(session, tenant_id=tenant.tenant_id, workflow_id=workflow_id)
    assert_org_access(org_scope, row.org_unit_id, session=session)
    if row.status != "draft":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WF_050",
                "message": "delete_draft_only",
                "hint": "published_cannot_delete",
            },
        )
    session.delete(row)
    session.commit()
    return {"ok": True, "id": workflow_id}
