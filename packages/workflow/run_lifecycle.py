"""Workflow run lifecycle — start, execute, resume, continue, cancel.

Patch note: names imported here (e.g. ``rebuild_tenant_context``) must be
mocked as ``packages.workflow.run_lifecycle.<name>``, not only on
``runner_shared``. See ``runner`` module docstring.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.errors import ErrorCode
from packages.org.scope import OrgScope, assert_org_access
from backend.database.pgvector_session import Workflow, WorkflowRun, WorkflowRunNode, get_pg_session
from packages.auth.models import TenantContext
from packages.workflow.composition import CompositionDepthExceeded, check_composition_budget
from packages.workflow.ir import WorkflowIR
from packages.workflow.node_exec import _execute_ir_ready_driven
from packages.workflow.run_parent import _wake_parent_after_fail, wake_parent
from packages.workflow.run_state import assert_transition
from packages.workflow.runner_shared import (
    MAX_RUNNING_ROOT_RUNS,
    RunSuspended,
    RunWaitingChild,
    _audit,
    _count_inflight_roots,
    _fail_run,
    _http_depth_exceeded,
    _notify_run_done,
    rebuild_tenant_context,
)

logger = logging.getLogger(__name__)

# Session-level lock: 崩溃后连接断开，PG 自动释放，不永久挂起。
_ADVISORY_LOCK_NS = b"nexusai:execute_run:"


def run_advisory_lock_key(run_id: str) -> int:
    """Stable positive int8 for ``pg_try_advisory_lock`` from ``run_id``."""
    digest = hashlib.sha256(_ADVISORY_LOCK_NS + run_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) & 0x7FFFFFFFFFFFFFFF


def _try_execute_lock(session: Session, run_id: str) -> bool:
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "sqlite":
        return True
    key = run_advisory_lock_key(run_id)
    try:
        return bool(
            session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
        )
    except Exception:
        logger.debug("pg_try_advisory_lock unavailable; skip run=%s", run_id)
        return True


def _unlock_execute(session: Session, run_id: str) -> None:
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "sqlite":
        return
    key = run_advisory_lock_key(run_id)
    try:
        session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
    except Exception:
        logger.debug("pg_advisory_unlock failed run=%s", run_id)


def start_run(
    session: Session,
    *,
    tenant: TenantContext,
    org_scope: OrgScope,
    workflow_id: str,
    parent_run_id: str | None = None,
    parent_node_id: str | None = None,
    run_inputs: dict[str, Any] | None = None,
    composition_depth: int | None = None,
    _internal_nested: bool = False,
) -> dict[str, Any]:
    if parent_run_id and not _internal_nested:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PARENT_FORGED",
                "message": "client_cannot_set_parent_run_id",
            },
        )
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

    depth = 0 if composition_depth is None else int(composition_depth)
    if parent_run_id:
        parent = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.id == parent_run_id)
            .one_or_none()
        )
        if parent is None:
            raise HTTPException(
                status_code=400,
                detail={"code": "PARENT_MISSING", "message": "parent_run_not_found"},
            )
        depth = int(getattr(parent, "composition_depth", 0) or 0) + 1
    try:
        check_composition_budget(depth, agent_stack=0)
    except CompositionDepthExceeded as exc:
        raise _http_depth_exceeded(exc) from exc

    if not parent_run_id:
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
    WorkflowIR.model_validate(ir_snap)

    inputs = dict(run_inputs or {})
    run = WorkflowRun(
        id=str(uuid.uuid4()),
        tenant_id=tenant.tenant_id,
        workflow_id=wf.id,
        org_unit_id=org_unit_id,
        status="pending",
        ir_snapshot=ir_snap,
        workflow_version=wf.version,
        workflow_revision=int(wf.revision),
        context_ref={"input": inputs} if inputs else None,
        run_inputs=inputs or None,
        parent_run_id=parent_run_id,
        parent_node_id=parent_node_id,
        composition_depth=depth,
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
        output_text=f"workflow_id={wf.id};parent={parent_run_id or ''}",
    )
    return {
        "id": run.id,
        "status": run.status,
        "workflow_id": run.workflow_id,
        "org_unit_id": run.org_unit_id,
        "parent_run_id": run.parent_run_id,
        "composition_depth": run.composition_depth,
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
            if not _try_execute_lock(session, run_id):
                logger.debug("execute_run lock busy run=%s", run_id)
                return
            try:
                run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one_or_none()
                if run is None:
                    return
                # 并发护栏 + CAS pending → running（子 run 豁免根配额）
                if run.parent_run_id is None and (
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

                try:
                    from packages.workflow.scheduler import validate_grants_before_execute

                    validate_grants_before_execute(
                        session,
                        tenant_id=run.tenant_id,
                        workflow_id=run.workflow_id,
                        acting_user_id=run.acting_user_id,
                    )
                    session.commit()
                except Exception as exc:
                    # I3 拍板：不得吞异常（fail-closed）
                    logger.exception("grant validate at execute failed run=%s", run_id)
                    _fail_run(
                        run_id,
                        error_code=ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS,
                        error_message=f"grant_validate_failed:{exc!s}"[:500],
                    )
                    return

                tenant, org_scope = rebuild_tenant_context(
                    session,
                    tenant_id=run.tenant_id,
                    acting_user_id=run.acting_user_id,
                    credential_kind=run.credential_kind,
                )

                ir = WorkflowIR.model_validate(dict(run.ir_snapshot or {}))
                await _execute_ir_ready_driven(
                    session,
                    run=run,
                    ir=ir,
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
                _notify_run_done(run, status="succeeded")
                if run.parent_run_id:
                    wake_parent(run.parent_run_id, run.parent_node_id or "", child_run_id=run.id)
            finally:
                _unlock_execute(session, run_id)
    except RunWaitingChild:
        return
    except RunSuspended:
        return
    except HTTPException as exc:
        _fail_run(run_id, error_code=str((exc.detail or {}).get("code") if isinstance(exc.detail, dict) else ErrorCode.RUN_500), error_message=str(exc.detail))
        _wake_parent_after_fail(run_id)
    except Exception as exc:
        logger.exception("execute_run failed run_id=%s", run_id)
        _fail_run(run_id, error_code=ErrorCode.RUN_500, error_message=str(exc)[:500])
        _wake_parent_after_fail(run_id)


def schedule_resume_or_continue(run_id: str) -> None:
    """Parent still running after child success — continue ready-driven loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(continue_run(run_id))
        return
    loop.create_task(continue_run(run_id))


async def continue_run(run_id: str) -> None:
    """Re-enter executor for a running parent after waiting_child clears."""
    sf = get_pg_session()
    try:
        with sf.Session() as session:
            run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one_or_none()
            if run is None or run.status != "running":
                return
            # Reentrancy gate: still has waiting_child → 409 semantics (no-op)
            still = (
                session.query(WorkflowRunNode)
                .filter(
                    WorkflowRunNode.run_id == run_id,
                    WorkflowRunNode.status == "waiting_child",
                )
                .first()
            )
            if still is not None:
                return
            tenant, org_scope = rebuild_tenant_context(
                session,
                tenant_id=run.tenant_id,
                acting_user_id=run.acting_user_id,
                credential_kind=run.credential_kind,
            )
            ir = WorkflowIR.model_validate(dict(run.ir_snapshot or {}))
            await _execute_ir_ready_driven(
                session,
                run=run,
                ir=ir,
                tenant=tenant,
                org_scope=org_scope,
            )
            run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
            if run.status != "running":
                return
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
            _notify_run_done(run, status="succeeded")
            if run.parent_run_id:
                wake_parent(
                    run.parent_run_id,
                    run.parent_node_id or "",
                    child_run_id=run.id,
                )
    except RunWaitingChild:
        return
    except RunSuspended:
        return
    except Exception as exc:
        logger.exception("continue_run failed run_id=%s", run_id)
        _fail_run(run_id, error_code=ErrorCode.RUN_500, error_message=str(exc)[:500])
        _wake_parent_after_fail(run_id)


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

            # E3.5 — 执行前授权校验
            try:
                from packages.workflow.scheduler import validate_grants_before_execute

                validate_grants_before_execute(
                    session,
                    tenant_id=run.tenant_id,
                    workflow_id=run.workflow_id,
                    acting_user_id=run.acting_user_id,
                )
                session.commit()
            except Exception as exc:
                # I3 拍板：不得吞异常（fail-closed）
                logger.exception("grant validate at resume failed run=%s", run_id)
                _fail_run(
                    run_id,
                    error_code=ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS,
                    error_message=f"grant_validate_failed:{exc!s}"[:500],
                )
                return

            tenant, org_scope = rebuild_tenant_context(
                session,
                tenant_id=run.tenant_id,
                acting_user_id=run.acting_user_id,
                credential_kind=run.credential_kind,
            )
            ir = WorkflowIR.model_validate(dict(run.ir_snapshot or {}))
            # 评审 08-14 回归修复:resume = 审批已到 → waiting 节点重置为 pending 重试
            # （R-C 就绪驱动循环把 waiting 当挂起信号,若不清零,resume 后循环首轮即
            #   raise RunSuspended,waiting 节点永远不会带 grant 重试,run 卡 running）
            session.execute(
                text(
                    "UPDATE workflow_run_nodes SET status='pending', error_message=NULL "
                    "WHERE run_id=:id AND status='waiting'"
                ),
                {"id": run_id},
            )
            session.commit()
            await _execute_ir_ready_driven(
                session,
                run=run,
                ir=ir,
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
            _notify_run_done(run, status="succeeded")
            if run.parent_run_id:
                wake_parent(
                    run.parent_run_id, run.parent_node_id or "", child_run_id=run.id
                )
    except RunWaitingChild:
        return
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
        _wake_parent_after_fail(run_id)
    except Exception as exc:
        logger.exception("resume_run failed run_id=%s", run_id)
        _fail_run(run_id, error_code=ErrorCode.RUN_500, error_message=str(exc)[:500])
        _wake_parent_after_fail(run_id)


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
    cancelled_meta: list[dict[str, Any]] = []
    for req in pending:
        req.status = "cancelled"
        req.updated_at = now
        req.review_reason = "run_cancelled"
        cancelled_meta.append(
            {
                "request_id": req.id,
                "node_id": req.node_id,
                "org_unit_id": req.org_unit_id,
                "capability_id": req.capability_id,
            }
        )
    session.commit()
    _audit(
        tenant_id=run.tenant_id,
        user_id=tenant.user_id,
        action="workflow.run.cancelled",
        credential_kind=run.credential_kind,
        run_id=run.id,
        output_text=f"requests_cancelled={len(pending)}",
    )
    # 撤销 → 审批人（dept_manager / tenant_admin）
    try:
        from packages.notification.service import (
            list_tenant_admin_user_ids,
            notify_many,
        )
        from packages.workflow.notify import resolve_hang_route

        for meta in cancelled_meta:
            route = resolve_hang_route(
                session,
                tenant_id=run.tenant_id,
                org_unit_id=meta["org_unit_id"],
            )
            targets = (
                list_tenant_admin_user_ids(session, run.tenant_id)
                if route.escalate_to_tenant_admin
                else list(route.manager_user_ids)
            )
            notify_many(
                run.tenant_id,
                targets,
                "hang.cancelled",
                {
                    "run_id": run.id,
                    "node_id": meta["node_id"],
                    "request_id": meta["request_id"],
                    "capability_id": meta["capability_id"],
                },
            )
    except Exception:
        logger.debug("cancel notify failed", exc_info=True)
    # 1A: cancelled is a terminal state — must wake parent (else forever waiting_child)
    if run.parent_run_id:
        wake_parent(
            run.parent_run_id,
            run.parent_node_id or "",
            child_run_id=run.id,
        )
    return {
        "id": run.id,
        "status": run.status,
        "requests_cancelled": len(pending),
    }
