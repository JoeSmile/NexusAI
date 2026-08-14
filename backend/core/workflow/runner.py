"""Workflow runner — start + execute (Wave D)."""

from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.audit import write_audit_sync
from backend.core.auth.models import TenantContext
from backend.core.capability.errors import CapabilityNotFoundError
from backend.core.capability.invoke import invoke
from backend.core.capability.registry import get_capability_registry
from backend.core.errors import ErrorCode, NexusAIException
from backend.core.guardrails.input_guard import detect_injection_in_params
from backend.core.org.scope import OrgScope, assert_org_access, resolve_org_scope
from backend.core.workflow.evidence import evidence_from_rag_sources, node_output
from backend.core.workflow.grants import (
    create_pending_request,
    expire_stale_approvals_for_node,
    find_active_grant_covering,
    grant_auth_context,
    is_eligible_approver,
    issue_auto_grant,
)
from backend.core.workflow.ir import WorkflowIR
from backend.core.workflow.run_state import assert_transition
from backend.core.workflow.security_gates import HangGateError, assert_hang_wait_allowed
from backend.core.workflow.service import capability_catalog_visible
from backend.database.pgvector_session import (
    Workflow,
    WorkflowRun,
    WorkflowRunNode,
    get_pg_session,
)

logger = logging.getLogger(__name__)

MAX_RUNNING_ROOT_RUNS = 2


class RunSuspended(Exception):
    """Node hung waiting for approval — executor exits cleanly (no fail)."""

    def __init__(self, run_id: str, node_id: str) -> None:
        self.run_id = run_id
        self.node_id = node_id
        super().__init__(f"run_suspended:{run_id}:{node_id}")


def _audit(
    *,
    tenant_id: str,
    user_id: str,
    action: str,
    credential_kind: str | None,
    run_id: str | None = None,
    node_id: str | None = None,
    error_code: str | None = None,
    output_text: str = "",
) -> None:
    write_audit_sync(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": action,
            "trace_id": run_id or "",
            "input_text": "",
            "output_text": output_text[:500] if output_text else "",
            "model": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
            "latency_ms": 0.0,
            "error_code": error_code,
            "ip_address": "",
            "user_agent": "",
            "credential_kind": credential_kind,
            "key_id": None,
            "run_id": run_id,
            "node_id": node_id,
            "created_at": datetime.utcnow(),
        }
    )


def rebuild_tenant_context(
    session: Session,
    *,
    tenant_id: str,
    acting_user_id: str,
    credential_kind: str | None,
) -> tuple[TenantContext, OrgScope]:
    row = session.execute(
        text(
            "SELECT user_id, tenant_id, role FROM users "
            "WHERE user_id = :uid AND tenant_id = :tid LIMIT 1"
        ),
        {"uid": acting_user_id, "tid": tenant_id},
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=400,
            detail={"code": ErrorCode.RUN_ACTING_USER_NOT_FOUND, "message": "acting_user_not_found"},
        )
    role = str(row.role)
    from backend.core.auth.session_auth import _load_extra_permissions

    extras = _load_extra_permissions(user_id=acting_user_id, tenant_id=tenant_id)
    scope = resolve_org_scope(
        session,
        tenant_id=tenant_id,
        user_id=acting_user_id,
        platform_role=role,
        is_cross_tenant=role in ("super_admin", "auditor"),
    )
    tenant = TenantContext(
        tenant_id=tenant_id,
        user_id=acting_user_id,
        role=role,
        extra_permissions=extras,
        is_cross_tenant=role in ("super_admin", "auditor"),
        credential_kind=credential_kind or "human_session",
        key_id=None,
        acting_user_id=acting_user_id,
        business_roles=sorted(scope.business_roles),
    )
    return tenant, scope


def _count_inflight_roots(
    session: Session, *, tenant_id: str, acting_user_id: str
) -> int:
    """在途根 run 数(pending+running)——拍板 08-12:并发配额按在途算,
    突发 N 个 POST 在 API 层就 429,不创建注定失败的 run。"""
    row = session.execute(
        text(
            "SELECT COUNT(*) AS c FROM workflow_runs "
            "WHERE tenant_id = :tid AND acting_user_id = :uid "
            "AND status IN ('pending', 'running') AND parent_run_id IS NULL"
        ),
        {"tid": tenant_id, "uid": acting_user_id},
    ).fetchone()
    return int(row.c if row else 0)


def start_run(
    session: Session,
    *,
    tenant: TenantContext,
    org_scope: OrgScope,
    workflow_id: str,
) -> dict[str, Any]:
    wf = (
        session.query(Workflow)
        .filter(Workflow.tenant_id == tenant.tenant_id, Workflow.id == workflow_id)
        .one_or_none()
    )
    if wf is None:
        raise HTTPException(
            status_code=404,
            detail={"code": ErrorCode.WF_NOT_FOUND, "message": "workflow_not_found"},
        )
    assert_org_access(org_scope, wf.org_unit_id, session=session)
    if wf.status != "published":
        raise HTTPException(
            status_code=409,
            detail={
                "code": ErrorCode.RUN_PUBLISH_FIRST,
                "message": "publish_first",
                "hint": "only_published_can_run",
            },
        )

    org_unit_id = org_scope.primary_org_unit_id
    if not org_unit_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": ErrorCode.RUN_PRIMARY_ORG_REQUIRED,
                "message": "primary_org_required",
                "hint": "bind_primary_org_unit",
            },
        )

    if _count_inflight_roots(
        session, tenant_id=tenant.tenant_id, acting_user_id=tenant.user_id
    ) >= MAX_RUNNING_ROOT_RUNS:
        raise HTTPException(
            status_code=429,
            detail={
                "code": ErrorCode.RUN_CONCURRENCY_LIMIT,
                "message": "too_many_running_runs",
            },
        )

    ir_snap = copy.deepcopy(dict(wf.ir_json or {}))
    # Validate snapshot shape (requestable ignored at execute)
    WorkflowIR.model_validate(ir_snap)

    run = WorkflowRun(
        id=str(uuid.uuid4()),
        tenant_id=tenant.tenant_id,
        workflow_id=wf.id,
        org_unit_id=org_unit_id,
        status="pending",
        ir_snapshot=ir_snap,
        workflow_version=wf.version,
        workflow_revision=int(wf.revision),
        context_ref=None,
        parent_run_id=None,
        acting_user_id=tenant.user_id,
        credential_kind=tenant.credential_kind,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    _audit(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        action="workflow.run.start",
        credential_kind=tenant.credential_kind,
        run_id=run.id,
        output_text=f"workflow_id={wf.id}",
    )
    return {
        "id": run.id,
        "status": run.status,
        "workflow_id": run.workflow_id,
        "org_unit_id": run.org_unit_id,
    }


def schedule_execute(run_id: str) -> None:
    """Fire-and-forget in-process task (MVP)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(execute_run(run_id))
        return
    loop.create_task(execute_run(run_id))


async def execute_run(run_id: str) -> None:
    sf = get_pg_session()
    try:
        with sf.Session() as session:
            run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one_or_none()
            if run is None:
                return
            # 并发护栏 + CAS pending → running
            if (
                _count_inflight_roots(
                    session,
                    tenant_id=run.tenant_id,
                    acting_user_id=run.acting_user_id,
                )
                >= MAX_RUNNING_ROOT_RUNS
            ):
                run.status = "failed"
                run.error_code = ErrorCode.RUN_CONCURRENCY_LIMIT
                run.error_message = "too_many_running_runs"
                run.finished_at = datetime.utcnow()
                session.commit()
                return  # 后台兜底:直接终态,不 raise(调用方已不可见)
            res = session.execute(
                text(
                    "UPDATE workflow_runs SET status='running', updated_at=:now "
                    "WHERE id=:id AND status='pending'"
                ),
                {"id": run_id, "now": datetime.utcnow()},
            )
            if res.rowcount != 1:
                # CAS 失败:另一个 executor 已持有(或 run 已终态)——不是失败,
                # 直接退出;绝不能走 _fail_run(会把胜者的 running 标 failed + 写错误审计)
                return
            session.commit()
            run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()

            tenant, org_scope = rebuild_tenant_context(
                session,
                tenant_id=run.tenant_id,
                acting_user_id=run.acting_user_id,
                credential_kind=run.credential_kind,
            )

            ir = WorkflowIR.model_validate(dict(run.ir_snapshot or {}))
            for node in ir.nodes:
                await _execute_node(
                    session,
                    run=run,
                    node=node.model_dump(),
                    tenant=tenant,
                    org_scope=org_scope,
                )

            run.status = "succeeded"
            run.finished_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
            _audit(
                tenant_id=run.tenant_id,
                user_id=run.acting_user_id,
                action="workflow.run.succeeded",
                credential_kind=run.credential_kind,
                run_id=run.id,
            )
    except RunSuspended:
        return
    except HTTPException as exc:
        _fail_run(run_id, error_code=str((exc.detail or {}).get("code") if isinstance(exc.detail, dict) else ErrorCode.RUN_500), error_message=str(exc.detail))
    except Exception as exc:
        logger.exception("execute_run failed run_id=%s", run_id)
        _fail_run(run_id, error_code=ErrorCode.RUN_500, error_message=str(exc)[:500])


def _fail_run(run_id: str, *, error_code: str, error_message: str) -> None:
    sf = get_pg_session()
    with sf.Session() as session:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one_or_none()
        if run is None:
            return
        if run.status in ("succeeded", "failed", "suspended", "cancelled"):
            return
        run.status = "failed"
        run.error_code = error_code[:64]
        run.error_message = error_message[:2000]
        run.finished_at = datetime.utcnow()
        run.updated_at = datetime.utcnow()
        session.commit()
        _audit(
            tenant_id=run.tenant_id,
            user_id=run.acting_user_id,
            action="workflow.run.failed",
            credential_kind=run.credential_kind,
            run_id=run.id,
            error_code=error_code,
            output_text=error_message[:200],
        )


async def _execute_node(
    session: Session,
    *,
    run: WorkflowRun,
    node: dict[str, Any],
    tenant: TenantContext,
    org_scope: OrgScope,
) -> None:
    node_id = str(node["node_id"])
    cap_id = str(node["capability_id"])
    params = dict(node.get("params") or {})
    # Wave D: ignore requestable — unauthorized always fails
    idem = f"{run.id}:{node_id}"

    existing = (
        session.query(WorkflowRunNode)
        .filter(WorkflowRunNode.idempotency_key == idem)
        .one_or_none()
    )
    if existing is not None and existing.status == "succeeded":
        return

    row = existing or WorkflowRunNode(
        id=str(uuid.uuid4()),
        run_id=run.id,
        node_id=node_id,
        status="pending",
        attempt=0,
        idempotency_key=idem,
    )
    if existing is None:
        session.add(row)
    row.status = "running"
    row.attempt = int(row.attempt or 0) + 1
    row.started_at = datetime.utcnow()
    session.commit()

    hit = detect_injection_in_params(params)
    if hit:
        row.status = "failed"
        row.error_message = f"injection:{hit}"
        row.finished_at = datetime.utcnow()
        session.commit()
        _audit(
            tenant_id=run.tenant_id,
            user_id=run.acting_user_id,
            action="workflow.node.injection",
            credential_kind=run.credential_kind,
            run_id=run.id,
            node_id=node_id,
            error_code=ErrorCode.RUN_INJECTION,
            output_text=cap_id,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "code": ErrorCode.RUN_INJECTION,
                "message": "params_injection",
                "capability_id": cap_id,
            },
        )

    reg = get_capability_registry()
    spec = reg.get(cap_id)
    if spec is None or not capability_catalog_visible(spec, tenant):
        # Distinguishes CAP_001-style hide vs missing
        row.status = "failed"
        row.error_message = "capability_not_found_or_hidden"
        row.finished_at = datetime.utcnow()
        session.commit()
        _audit(
            tenant_id=run.tenant_id,
            user_id=run.acting_user_id,
            action="workflow.node.auth_fail",
            credential_kind=run.credential_kind,
            run_id=run.id,
            node_id=node_id,
            error_code=ErrorCode.CAP_NOT_FOUND,
            output_text=cap_id,
        )
        raise HTTPException(
            status_code=404,
            detail={"code": ErrorCode.CAP_NOT_FOUND, "message": "capability_not_found", "capability_id": cap_id},
        )

    needed = (spec.permission or "").strip()
    if not needed:
        # 拍板 08-12:未声明 permission 的 capability 默认不可跑(防误放行)
        row.status = "failed"
        row.error_message = "capability_missing_permission_declaration"
        row.finished_at = datetime.utcnow()
        session.commit()
        _audit(
            tenant_id=run.tenant_id,
            user_id=run.acting_user_id,
            action="workflow.node.auth_fail",
            credential_kind=run.credential_kind,
            run_id=run.id,
            node_id=node_id,
            error_code=ErrorCode.RUN_500,
            output_text=cap_id,
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": ErrorCode.RUN_500,
                "message": "capability_missing_permission",
                "capability_id": cap_id,
            },
        )

    has_perm = tenant.has_permission(needed, org_scope=org_scope)
    grant_hit = find_active_grant_covering(
        session,
        tenant_id=run.tenant_id,
        workflow_id=run.workflow_id,
        applicant_user_id=run.acting_user_id,
        capability_id=cap_id,
    )
    if not has_perm and grant_hit is None:
        # Wave E2: requestable 三态 → suspend / auto-grant / fail-closed
        try:
            gate = assert_hang_wait_allowed(
                tenant=tenant,
                org_scope=org_scope,
                node_requestable=node.get("requestable"),
                capability=spec,
            )
        except HangGateError as exc:
            row.status = "failed"
            row.error_message = f"auth_denied:{needed}:{exc.code}"
            row.finished_at = datetime.utcnow()
            session.commit()
            _audit(
                tenant_id=run.tenant_id,
                user_id=run.acting_user_id,
                action="workflow.node.auth_fail",
                credential_kind=run.credential_kind,
                run_id=run.id,
                node_id=node_id,
                error_code=ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS,
                output_text=f"{cap_id}:{needed}:{exc.code}",
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS,
                    "message": "permission_denied",
                    "needed_perm": needed,
                    "capability_id": cap_id,
                    "gate": exc.code,
                },
            ) from exc

        mode = gate.requestable
        note = node.get("approval_note")
        note_s = str(note).strip() if note else None

        wf_row = (
            session.query(Workflow)
            .filter(Workflow.id == run.workflow_id)
            .one_or_none()
        )
        policy = dict(wf_row.request_policy) if wf_row and wf_row.request_policy else None

        if is_eligible_approver(
            tenant,
            org_scope,
            resource_org_unit_id=run.org_unit_id,
            requestable_mode=mode,
            session=session,
        ):
            issue_auto_grant(
                session,
                tenant_id=run.tenant_id,
                workflow_id=run.workflow_id,
                run_id=run.id,
                node_id=node_id,
                applicant_user_id=run.acting_user_id,
                needed_perm=needed,
                org_unit_id=run.org_unit_id,
                capability_id=cap_id,
                requestable_mode=mode,
                approval_note=note_s,
                request_policy=policy,
            )
            session.commit()
            _audit(
                tenant_id=run.tenant_id,
                user_id=run.acting_user_id,
                action="workflow.auto_grant",
                credential_kind="delegation",
                run_id=run.id,
                node_id=node_id,
                output_text=f"{cap_id}:{needed}:self_approve",
            )
            # fall through → invoke with grant context
        else:
            assert_transition(run.status, "suspended")
            run.status = "suspended"
            run.updated_at = datetime.utcnow()
            row.status = "waiting"
            row.error_message = f"waiting_approval:{needed}"
            expire_stale_approvals_for_node(
                session,
                tenant_id=run.tenant_id,
                workflow_id=run.workflow_id,
                run_id=run.id,
                node_id=node_id,
                applicant_user_id=run.acting_user_id,
                capability_id=cap_id,
            )
            create_pending_request(
                session,
                tenant_id=run.tenant_id,
                run_id=run.id,
                node_id=node_id,
                applicant_user_id=run.acting_user_id,
                needed_perm=needed,
                org_unit_id=run.org_unit_id,
                capability_id=cap_id,
                requestable_mode=mode,
                approval_note=note_s,
            )
            session.commit()
            _audit(
                tenant_id=run.tenant_id,
                user_id=run.acting_user_id,
                action="workflow.run.suspended",
                credential_kind=run.credential_kind,
                run_id=run.id,
                node_id=node_id,
                output_text=f"{cap_id}:{needed}:{mode}",
            )
            # E3: notify_hang_pending async (silent)
            try:
                from backend.core.workflow.notify import notify_hang_pending

                notify_hang_pending(run.id, node_id)
            except Exception:
                logger.debug("hang notify skipped", exc_info=True)
            raise RunSuspended(run.id, node_id)

    try:
        text_parts: list[str] = []
        done_meta: dict[str, Any] = {}
        with grant_auth_context(
            tenant_id=run.tenant_id,
            workflow_id=run.workflow_id,
            applicant_user_id=run.acting_user_id,
            capability_id=cap_id,
        ):
            async for frame in invoke(cap_id, params, tenant):
                ev = frame.get("event")
                if ev == "token":
                    text_parts.append(str(frame.get("data") or ""))
                elif ev == "done":
                    done_meta = dict(frame.get("data") or {})
        answer = "".join(text_parts)
        sources = done_meta.get("sources")
        if not isinstance(sources, list):
            sources = []
        # 仅真实 sources → evidence；空命中保持 []（禁止 answer 合成）
        evidence = evidence_from_rag_sources(sources, node_id=node_id)
        row.output_json = node_output(
            result={"answer": answer, "done": {k: v for k, v in done_meta.items() if k != "sources"}},
            evidence=evidence,
        )
        row.status = "succeeded"
        row.finished_at = datetime.utcnow()
        session.commit()
        _audit(
            tenant_id=run.tenant_id,
            user_id=run.acting_user_id,
            action="workflow.node.succeeded",
            credential_kind=run.credential_kind,
            run_id=run.id,
            node_id=node_id,
            output_text=f"evidence_count={len(evidence)}",
        )
    except CapabilityNotFoundError as exc:
        row.status = "failed"
        row.error_message = str(ErrorCode.CAP_NOT_FOUND)
        row.finished_at = datetime.utcnow()
        session.commit()
        raise HTTPException(
            status_code=404,
            detail={"code": ErrorCode.CAP_NOT_FOUND, "message": str(exc), "capability_id": cap_id},
        ) from exc
    except NexusAIException as exc:
        code = getattr(exc, "code", None) or ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS
        code_s = getattr(code, "value", None) or str(code)
        row.status = "failed"
        row.error_message = code_s
        row.finished_at = datetime.utcnow()
        session.commit()
        raise HTTPException(
            status_code=403,
            detail={"code": code_s, "message": str(exc), "capability_id": cap_id},
        ) from exc
    except Exception as exc:
        row.status = "failed"
        row.error_message = str(exc)[:500]
        row.finished_at = datetime.utcnow()
        session.commit()
        raise


def mark_zombie_runs_failed() -> int:
    """Startup: leftover running → failed + audit."""
    sf = get_pg_session()
    n = 0
    with sf.Session() as session:
        rows = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.status == "running")
            .all()
        )
        for run in rows:
            run.status = "failed"
            run.error_code = ErrorCode.RUN_ZOMBIE
            run.error_message = "process_restart_marked_failed"
            run.finished_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            n += 1
            _audit(
                tenant_id=run.tenant_id,
                user_id=run.acting_user_id,
                action="workflow.run.zombie",
                credential_kind=run.credential_kind,
                run_id=run.id,
                error_code=ErrorCode.RUN_ZOMBIE,
            )
        session.commit()
    return n


def schedule_resume(run_id: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(resume_run(run_id))
        return
    loop.create_task(resume_run(run_id))


async def resume_run(run_id: str) -> None:
    """suspended → running CAS；跳过已 succeeded 节点，waiting/未完成重鉴权。"""
    sf = get_pg_session()
    try:
        with sf.Session() as session:
            res = session.execute(
                text(
                    "UPDATE workflow_runs SET status='running', updated_at=:now, "
                    "error_code=NULL, error_message=NULL "
                    "WHERE id=:id AND status='suspended'"
                ),
                {"id": run_id, "now": datetime.utcnow()},
            )
            if res.rowcount != 1:
                return
            session.commit()
            run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()

            tenant, org_scope = rebuild_tenant_context(
                session,
                tenant_id=run.tenant_id,
                acting_user_id=run.acting_user_id,
                credential_kind=run.credential_kind,
            )
            ir = WorkflowIR.model_validate(dict(run.ir_snapshot or {}))
            for node in ir.nodes:
                await _execute_node(
                    session,
                    run=run,
                    node=node.model_dump(),
                    tenant=tenant,
                    org_scope=org_scope,
                )

            # 若中途又挂起，_execute_node 抛 RunSuspended
            run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
            if run.status == "suspended":
                return
            # CAS: 仅 running → succeeded（评审 M-1）——避免与并发 cancel 互相覆盖
            res2 = session.execute(
                text(
                    "UPDATE workflow_runs SET status='succeeded', finished_at=:now, "
                    "updated_at=:now WHERE id=:id AND status='running'"
                ),
                {"id": run_id, "now": datetime.utcnow()},
            )
            session.commit()
            if res2.rowcount != 1:
                return  # 已被并发 cancel/fail 收走,不再写成功
            _audit(
                tenant_id=run.tenant_id,
                user_id=run.acting_user_id,
                action="workflow.run.succeeded",
                credential_kind=run.credential_kind or "delegation",
                run_id=run.id,
            )
    except RunSuspended:
        return
    except HTTPException as exc:
        _fail_run(
            run_id,
            error_code=str(
                (exc.detail or {}).get("code")
                if isinstance(exc.detail, dict)
                else ErrorCode.RUN_500
            ),
            error_message=str(exc.detail),
        )
    except Exception as exc:
        logger.exception("resume_run failed run_id=%s", run_id)
        _fail_run(run_id, error_code=ErrorCode.RUN_500, error_message=str(exc)[:500])


def cancel_run(
    session: Session,
    *,
    tenant: TenantContext,
    org_scope: OrgScope,
    run_id: str,
) -> dict[str, Any]:
    """pending/running/suspended → cancelled；挂起 request 同步 cancelled。"""
    from backend.database.pgvector_session import PermissionRequest

    run = (
        session.query(WorkflowRun)
        .filter(WorkflowRun.tenant_id == tenant.tenant_id, WorkflowRun.id == run_id)
        .one_or_none()
    )
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"code": ErrorCode.RUN_NOT_FOUND, "message": "run_not_found"},
        )
    assert_org_access(org_scope, run.org_unit_id, session=session)
    if run.status not in ("pending", "running", "suspended"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": ErrorCode.RUN_CAS_CONFLICT,
                "message": "cannot_cancel",
                "status": run.status,
            },
        )
    assert_transition(run.status, "cancelled")
    run.status = "cancelled"
    run.finished_at = datetime.utcnow()
    run.updated_at = datetime.utcnow()
    run.error_code = None
    run.error_message = "cancelled_by_user"
    pending = (
        session.query(PermissionRequest)
        .filter(
            PermissionRequest.run_id == run_id,
            PermissionRequest.status == "pending",
        )
        .all()
    )
    now = datetime.utcnow()
    for req in pending:
        req.status = "cancelled"
        req.updated_at = now
        req.review_reason = "run_cancelled"
    session.commit()
    _audit(
        tenant_id=run.tenant_id,
        user_id=tenant.user_id,
        action="workflow.run.cancelled",
        credential_kind=run.credential_kind,
        run_id=run.id,
        output_text=f"requests_cancelled={len(pending)}",
    )
    return {
        "id": run.id,
        "status": run.status,
        "requests_cancelled": len(pending),
    }


def freeze_ir_snapshot(ir: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(ir)


def idempotency_key(run_id: str, node_id: str) -> str:
    return f"{run_id}:{node_id}"
