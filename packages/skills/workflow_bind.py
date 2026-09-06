"""Task 1b — bind workflow-type Skills to published Workflow rows."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from packages.database.pgvector_session import Workflow
from packages.skills.base import BaseSkill, SkillResult
from packages.skills.types import SkillType
from packages.workflow.ir import WorkflowIR

logger = logging.getLogger(__name__)

HOTSPOT_LOGICAL_KEY = "builtin:hotspot"


def _stable_workflow_id(*, skill_id: str, tenant_id: str) -> str:
    digest = hashlib.sha256(f"builtin:skill:{skill_id}:{tenant_id}".encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def _upsert_ir_workflow(
    session: Session,
    *,
    tenant_id: str,
    skill: BaseSkill,
    created_by: str = "system",
) -> str:
    ir = WorkflowIR.model_validate(skill.workflow_ir or {})
    wid = _stable_workflow_id(skill_id=skill.id, tenant_id=tenant_id)
    now = datetime.utcnow()
    row = (
        session.query(Workflow)
        .filter(Workflow.tenant_id == tenant_id, Workflow.id == wid)
        .one_or_none()
    )
    name = f"内置·Skill:{skill.id}"
    ir_json = ir.model_dump(mode="json")
    if row is None:
        row = Workflow(
            id=wid,
            tenant_id=tenant_id,
            org_unit_id=None,
            name=name,
            status="published",
            ir_json=ir_json,
            version="V1.0.0",
            revision=1,
            forked_from_id=None,
            created_by=created_by or "system",
            intent_tags=list(skill.trigger_intents or []),
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
    if row.ir_json != ir_json:
        row.ir_json = ir_json
        changed = True
    if row.name != name:
        row.name = name
        changed = True
    if changed:
        row.updated_at = now
        session.flush()
    return row.id


def resolve_workflow_id(
    session: Session,
    *,
    tenant_id: str,
    skill: BaseSkill,
    created_by: str = "system",
) -> str:
    """Resolve a workflow-type Skill to a tenant published Workflow id.

    Logical keys (e.g. builtin:hotspot) reuse content_ops seed rows.
    Class ``workflow_ir`` is upserted as a published Workflow row.
    """
    if skill.skill_type != SkillType.WORKFLOW:
        raise ValueError(f"skill {skill.id}: not type=workflow")

    key = (skill.workflow_asset_id or "").strip()
    if key == HOTSPOT_LOGICAL_KEY:
        from packages.content_ops.workflow_seed import (
            ensure_builtin_hotspot_workflow,
        )

        return ensure_builtin_hotspot_workflow(
            session,
            tenant_id=tenant_id,
            created_by=created_by,
        )
    if key:
        raise ValueError(f"skill {skill.id}: unknown workflow_asset_id logical key: {key}")
    if skill.workflow_ir:
        return _upsert_ir_workflow(
            session,
            tenant_id=tenant_id,
            skill=skill,
            created_by=created_by,
        )
    raise ValueError(f"skill {skill.id}: type=workflow 缺少可解析载体")


def ensure_skill_workflows_published(
    session: Session,
    *,
    tenant_id: str,
    created_by: str = "system",
) -> dict[str, str]:
    """Upsert published Workflow rows for every workflow-type Skill."""
    from packages.skills.registry import SKILL_REGISTRY

    out: dict[str, str] = {}
    for skill in SKILL_REGISTRY.values():
        if skill.skill_type != SkillType.WORKFLOW:
            continue
        out[skill.id] = resolve_workflow_id(
            session,
            tenant_id=tenant_id,
            skill=skill,
            created_by=created_by,
        )
    return out


def _run_inputs_from_entities(
    skill: BaseSkill,
    entities: dict[str, Any],
) -> dict[str, Any]:
    ir = WorkflowIR.model_validate(skill.workflow_ir or {"nodes": []})
    if not ir.inputs:
        # hotspot logical carrier: topic from entities / message
        topic = entities.get("topic") or entities.get("theme") or entities.get("query")
        if topic:
            return {"topic": str(topic)[:500]}
        return {}
    out: dict[str, Any] = {}
    for name in ir.inputs:
        if name in entities and entities[name] is not None:
            out[name] = entities[name]
    return out


def start_skill_workflow_run(
    *,
    skill: BaseSkill,
    entities: dict[str, Any],
    tenant_id: str,
    user_context: dict[str, Any] | None = None,
) -> SkillResult:
    """Resolve published Workflow + start_run for a workflow-type Skill."""
    from packages.auth.models import TenantContext
    from packages.database.pgvector_session import get_pg_session
    from packages.org.scope import resolve_org_scope
    from packages.workflow import runner as run_svc

    uc = user_context or {}
    if not tenant_id:
        return SkillResult(
            success=False,
            error="SKILL_TENANT",
            output="缺少 tenant_id，无法启动 workflow",
        )
    tenant = TenantContext(
        tenant_id=tenant_id,
        user_id=str(uc.get("user_id") or ""),
        role=str(uc.get("role") or "user"),
        extra_permissions=list(uc.get("permissions") or []),
        is_cross_tenant=bool(uc.get("is_cross_tenant")),
    )
    try:
        sf = get_pg_session()
        with sf.Session() as session:
            wid = resolve_workflow_id(
                session,
                tenant_id=tenant_id,
                skill=skill,
                created_by=tenant.user_id or "system",
            )
            scope = resolve_org_scope(
                session,
                tenant_id=tenant.tenant_id,
                user_id=tenant.user_id,
                platform_role=tenant.role,
                is_cross_tenant=tenant.is_cross_tenant,
            )
            started = run_svc.start_run(
                session,
                tenant=tenant,
                org_scope=scope,
                workflow_id=wid,
                run_inputs=_run_inputs_from_entities(skill, entities),
            )
            session.commit()
        run_id = started.get("id") if isinstance(started, dict) else None
        if run_id:
            try:
                run_svc.schedule_execute(run_id)
            except Exception:
                logger.debug("schedule_execute skipped", exc_info=True)
        return SkillResult(
            success=True,
            output=f"已启动工作流（workflow_id={wid}, run_id={run_id}）",
        )
    except Exception as exc:
        logger.warning("skill workflow start failed: %s", exc, exc_info=True)
        code = "WORKFLOW_START_FAILED"
        detail = getattr(exc, "detail", None)
        if isinstance(detail, dict) and detail.get("code"):
            code = str(detail["code"])
        return SkillResult(
            success=False,
            error=code,
            output=str(exc),
        )
