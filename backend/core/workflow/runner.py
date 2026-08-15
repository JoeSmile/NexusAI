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
from backend.core.workflow.composition import (
    CompositionDepthExceeded,
    check_composition_budget,
)
from backend.core.workflow.evidence import evidence_from_rag_sources, node_output
from backend.core.workflow.grants import (
    create_pending_request,
    expire_stale_approvals_for_node,
    find_active_grant_covering,
    grant_auth_context,
    is_eligible_approver,
    issue_auto_grant,
)
from backend.core.workflow.ir import WorkflowIR, validate_params_against_spec
from backend.core.workflow.run_state import assert_node_transition, assert_transition
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


def _set_node_status(row: WorkflowRunNode, status: str) -> None:
    """评审 08-14 I-5:节点状态走转移表(此前 assert_node_transition 零调用,表形同虚设)。"""
    assert_node_transition(str(row.status or "pending"), status)
    row.status = status


def _http_depth_exceeded(exc: CompositionDepthExceeded) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "code": "DEPTH_EXCEEDED",
            "message": "composition_depth_exceeded",
            "depth": exc.total,
            "run_depth": exc.run_depth,
            "agent_stack": exc.agent_stack,
            "max": exc.max_depth,
        },
    )


class RunSuspended(Exception):
    """Node hung waiting for approval — executor exits cleanly (no fail)."""


class RunWaitingChild(Exception):
    """Parent node waiting on nested child run — keep parent running, exit executor."""

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


def _notify_run_done(run: WorkflowRun, *, status: str) -> None:
    try:
        from backend.modules.notification.service import notify_run_terminal

        inputs = _run_inputs_from_context(run)
        notify_run_terminal(
            tenant_id=run.tenant_id,
            user_id=run.acting_user_id,
            run_id=run.id,
            workflow_id=run.workflow_id,
            status=status,
            conversation_id=str(inputs.get("conversation_id") or "") or None,
            platform=str(inputs.get("platform") or "") or None,
            error_code=run.error_code,
            # 44.4 拍板 4A: never pass error_message; service fills friendly summary
        )
    except Exception:
        logger.debug("run terminal notify failed", exc_info=True)


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
        _notify_run_done(run, status="failed")


def _run_inputs_from_context(run: WorkflowRun) -> dict[str, Any]:
    """R-A: run_inputs column preferred; fall back to context_ref.input."""
    raw_inputs = getattr(run, "run_inputs", None)
    if isinstance(raw_inputs, dict) and raw_inputs:
        return dict(raw_inputs)
    raw = run.context_ref
    if not isinstance(raw, dict):
        return {}
    nested = raw.get("input")
    if isinstance(nested, dict):
        return dict(nested)
    return dict(raw)


def _load_node_statuses(
    session: Session, run_id: str, ir: WorkflowIR
) -> dict[str, str]:
    rows = (
        session.query(WorkflowRunNode)
        .filter(WorkflowRunNode.run_id == run_id)
        .all()
    )
    by_id = {r.node_id: r.status for r in rows}
    return {n.node_id: by_id.get(n.node_id, "pending") for n in ir.nodes}


def _collect_outputs(session: Session, run_id: str) -> dict[str, Any]:
    rows = (
        session.query(WorkflowRunNode)
        .filter(
            WorkflowRunNode.run_id == run_id,
            WorkflowRunNode.status == "succeeded",
        )
        .all()
    )
    out: dict[str, Any] = {}
    for r in rows:
        if isinstance(r.output_json, dict):
            out[r.node_id] = r.output_json
    return out


async def _execute_ir_ready_driven(
    session: Session,
    *,
    run: WorkflowRun,
    ir: WorkflowIR,
    tenant: TenantContext,
    org_scope: OrgScope,
) -> None:
    """R-C: serially execute ready nodes (preds succeeded/skipped); empty edges → IR order."""
    from backend.core.workflow.dataflow import (
        DataflowError,
        apply_edge_bindings,
        eval_run_if,
        pick_next_ready,
        resolve_params,
    )

    inputs = _run_inputs_from_context(run)
    guard = 0
    while guard < 500:
        guard += 1
        statuses = _load_node_statuses(session, run.id, ir)
        if all(statuses.get(n.node_id) in ("succeeded", "skipped", "failed") for n in ir.nodes):
            if any(statuses.get(n.node_id) == "failed" for n in ir.nodes):
                raise HTTPException(
                    status_code=400,
                    detail={"code": ErrorCode.RUN_500, "message": "node_failed"},
                )
            return
        if any(statuses.get(n.node_id) == "waiting" for n in ir.nodes):
            # hang path already suspended the run
            raise RunSuspended()
        if any(statuses.get(n.node_id) == "waiting_child" for n in ir.nodes):
            wc_node = next(
                (n.node_id for n in ir.nodes if statuses.get(n.node_id) == "waiting_child"),
                "",
            )
            raise RunWaitingChild(run.id, wc_node)

        node = pick_next_ready(ir, statuses)
        if node is None:
            pending = [n.node_id for n, st in ((n, statuses[n.node_id]) for n in ir.nodes) if st == "pending"]
            if pending:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "IR_DEADLOCK",
                        "message": "no_ready_nodes",
                        "pending": pending,
                    },
                )
            return

        outputs = _collect_outputs(session, run.id)
        try:
            if not eval_run_if(node.run_if, outputs=outputs, inputs=inputs):
                _mark_node_skipped(session, run=run, node_id=node.node_id)
                continue
            params = apply_edge_bindings(
                ir, node.node_id, dict(node.params or {}), outputs=outputs
            )
            params = resolve_params(params, outputs=outputs, inputs=inputs)
            # 评审 08-14 I-2:运行时类型校验(引用解析后)——保存期只验字面量,
            # ${output}/${input} 解析出的类型错在此拦截 → REF_TYPE_MISMATCH → 节点 failed
            if node.kind == "capability" and node.capability_id:
                try:
                    _spec = get_capability_registry().get(node.capability_id)
                    _ps = (
                        dict(_spec.param_spec)
                        if _spec is not None and _spec.param_spec
                        else None
                    )
                    validate_params_against_spec(params, _ps, allow_unresolved_refs=False)
                except ValueError as exc:
                    raise DataflowError("REF_TYPE_MISMATCH", str(exc)) from exc
        except DataflowError as exc:
            _fail_node_ref(
                session,
                run=run,
                node_id=node.node_id,
                code=exc.code,
                message=str(exc),
            )
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": str(exc), "node_id": node.node_id},
            ) from exc

        payload = node.model_dump()
        payload["params"] = params
        await _execute_node(
            session,
            run=run,
            node=payload,
            tenant=tenant,
            org_scope=org_scope,
        )


def _mark_node_skipped(session: Session, *, run: WorkflowRun, node_id: str) -> None:
    idem = f"{run.id}:{node_id}"
    row = (
        session.query(WorkflowRunNode)
        .filter(WorkflowRunNode.idempotency_key == idem)
        .one_or_none()
    )
    if row is None:
        row = WorkflowRunNode(
            id=str(uuid.uuid4()),
            run_id=run.id,
            node_id=node_id,
            status="skipped",
            attempt=0,
            idempotency_key=idem,
            finished_at=datetime.utcnow(),
        )
        session.add(row)
    else:
        _set_node_status(row, "skipped")
        row.finished_at = datetime.utcnow()
    session.commit()


def _fail_node_ref(
    session: Session,
    *,
    run: WorkflowRun,
    node_id: str,
    code: str,
    message: str,
) -> None:
    idem = f"{run.id}:{node_id}"
    row = (
        session.query(WorkflowRunNode)
        .filter(WorkflowRunNode.idempotency_key == idem)
        .one_or_none()
    )
    if row is None:
        row = WorkflowRunNode(
            id=str(uuid.uuid4()),
            run_id=run.id,
            node_id=node_id,
            status="failed",
            attempt=1,
            idempotency_key=idem,
            error_message=message[:2000],
            finished_at=datetime.utcnow(),
        )
        session.add(row)
    else:
        _set_node_status(row, "failed")
        row.error_message = message[:2000]
        row.finished_at = datetime.utcnow()
    session.commit()
    _audit(
        tenant_id=run.tenant_id,
        user_id=run.acting_user_id,
        action="workflow.node.ref_fail",
        credential_kind=run.credential_kind,
        run_id=run.id,
        node_id=node_id,
        error_code=code,
        output_text=message[:200],
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
    kind = str(node.get("kind") or "capability")
    if kind == "workflow":
        await _execute_workflow_node(
            session,
            run=run,
            node=node,
            tenant=tenant,
            org_scope=org_scope,
        )
        return
    if kind == "agent":
        await _execute_agent_node(
            session,
            run=run,
            node=node,
            tenant=tenant,
            org_scope=org_scope,
        )
        return
    if kind != "capability":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "KIND_NOT_IMPLEMENTED",
                "message": f"kind={kind} unknown",
                "node_id": node_id,
            },
        )
    cap_id = str(node.get("capability_id") or "")
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
    _set_node_status(row, "running")
    row.attempt = int(row.attempt or 0) + 1
    row.started_at = datetime.utcnow()
    session.commit()

    hit = detect_injection_in_params(params)
    if hit:
        _set_node_status(row, "failed")
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
        _set_node_status(row, "failed")
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
        _set_node_status(row, "failed")
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
            _set_node_status(row, "failed")
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
            _set_node_status(row, "waiting")
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
        _set_node_status(row, "succeeded")
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
        _set_node_status(row, "failed")
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
        _set_node_status(row, "failed")
        row.error_message = code_s
        row.finished_at = datetime.utcnow()
        session.commit()
        raise HTTPException(
            status_code=403,
            detail={"code": code_s, "message": str(exc), "capability_id": cap_id},
        ) from exc
    except Exception as exc:
        _set_node_status(row, "failed")
        row.error_message = str(exc)[:500]
        row.finished_at = datetime.utcnow()
        session.commit()
        raise


def mark_zombie_runs_failed() -> int:
    """Startup: leftover running → failed + audit; exempt waiting_child parents."""
    sf = get_pg_session()
    n = 0
    with sf.Session() as session:
        rows = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.status == "running")
            .all()
        )
        for run in rows:
            waiting_child = (
                session.query(WorkflowRunNode)
                .filter(
                    WorkflowRunNode.run_id == run.id,
                    WorkflowRunNode.status == "waiting_child",
                )
                .first()
            )
            if waiting_child is not None:
                continue
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


def recover_waiting_child_parents() -> int:
    """Startup (2A): waiting_child + child already terminal → wake_parent."""
    sf = get_pg_session()
    wakes: list[tuple[str, str, str]] = []
    with sf.Session() as session:
        waiting = (
            session.query(WorkflowRunNode)
            .filter(WorkflowRunNode.status == "waiting_child")
            .all()
        )
        for row in waiting:
            child = (
                session.query(WorkflowRun)
                .filter(
                    WorkflowRun.parent_run_id == row.run_id,
                    WorkflowRun.parent_node_id == row.node_id,
                    WorkflowRun.status.in_(("succeeded", "failed", "cancelled")),
                )
                .order_by(WorkflowRun.finished_at.desc().nullslast())
                .first()
            )
            if child is None:
                continue
            wakes.append((row.run_id, row.node_id, child.id))
    for parent_run_id, parent_node_id, child_run_id in wakes:
        try:
            wake_parent(parent_run_id, parent_node_id, child_run_id=child_run_id)
        except Exception:
            logger.debug(
                "recover waiting_child failed parent=%s child=%s",
                parent_run_id,
                child_run_id,
                exc_info=True,
            )
    return len(wakes)


async def _execute_workflow_node(
    session: Session,
    *,
    run: WorkflowRun,
    node: dict[str, Any],
    tenant: TenantContext,
    org_scope: OrgScope,
) -> None:
    """kind=workflow → nested start_run; parent node → waiting_child."""
    node_id = str(node["node_id"])
    child_wf_id = str(node.get("workflow_id") or "")
    idem = f"{run.id}:{node_id}"
    existing = (
        session.query(WorkflowRunNode)
        .filter(WorkflowRunNode.idempotency_key == idem)
        .one_or_none()
    )
    if existing is not None and existing.status in ("succeeded", "waiting_child"):
        if existing.status == "waiting_child":
            raise RunWaitingChild(run.id, node_id)
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
    _set_node_status(row, "running")
    row.attempt = int(row.attempt or 0) + 1
    row.started_at = datetime.utcnow()
    session.commit()

    # Live org resolve for child (D15 §1.2)
    child_scope = resolve_org_scope(
        session,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        platform_role=tenant.role,
        is_cross_tenant=tenant.is_cross_tenant,
    )
    child_inputs = dict(node.get("params") or {})
    started = start_run(
        session,
        tenant=tenant,
        org_scope=child_scope,
        workflow_id=child_wf_id,
        parent_run_id=run.id,
        parent_node_id=node_id,
        run_inputs=child_inputs,
        _internal_nested=True,
    )
    _set_node_status(row, "waiting_child")
    row.output_json = {
        "child_run_id": started["id"],
        "status": "pending",
        "outputs": None,
    }
    session.commit()
    schedule_execute(started["id"])
    raise RunWaitingChild(run.id, node_id)


async def _execute_agent_node(
    session: Session,
    *,
    run: WorkflowRun,
    node: dict[str, Any],
    tenant: TenantContext,
    org_scope: OrgScope,
) -> None:
    """kind=agent → same-run Hub agent chain (no child workflow_runs)."""
    depth = int(getattr(run, "composition_depth", 0) or 0)
    # Entering one agent layer; Hub recursions pass agent_stack via payload.
    try:
        check_composition_budget(depth, agent_stack=1)
    except CompositionDepthExceeded as exc:
        raise _http_depth_exceeded(exc) from exc
    forged = dict(node)
    forged["kind"] = "capability"
    forged["capability_id"] = str(node.get("agent_id") or "")
    forged.pop("agent_id", None)
    params = dict(forged.get("params") or {})
    params["_composition_run_depth"] = depth
    forged["params"] = params
    await _execute_node(
        session,
        run=run,
        node=forged,
        tenant=tenant,
        org_scope=org_scope,
    )


def _child_terminal_outputs(session: Session, child: WorkflowRun) -> Any:
    ir = WorkflowIR.model_validate(dict(child.ir_snapshot or {}))
    if not ir.nodes:
        return None
    # 评审 08-14 Minor5:IR 声明 output_node_id 则优先取该节点输出(缺省=最后 succeeded)
    if ir.output_node_id:
        row = (
            session.query(WorkflowRunNode)
            .filter(
                WorkflowRunNode.run_id == child.id,
                WorkflowRunNode.node_id == ir.output_node_id,
                WorkflowRunNode.status == "succeeded",
            )
            .one_or_none()
        )
        if row is not None:
            return row.output_json
    last_id = ir.nodes[-1].node_id
    for n in reversed(ir.nodes):
        row = (
            session.query(WorkflowRunNode)
            .filter(
                WorkflowRunNode.run_id == child.id,
                WorkflowRunNode.node_id == n.node_id,
                WorkflowRunNode.status == "succeeded",
            )
            .one_or_none()
        )
        if row is not None:
            return row.output_json
    row = (
        session.query(WorkflowRunNode)
        .filter(
            WorkflowRunNode.run_id == child.id,
            WorkflowRunNode.node_id == last_id,
        )
        .one_or_none()
    )
    return row.output_json if row else None


def wake_parent(
    parent_run_id: str,
    parent_node_id: str,
    *,
    child_run_id: str,
) -> None:
    """DB-reentrant: child terminal → update parent waiting_child node; schedule parent."""
    if not parent_run_id or not parent_node_id:
        return
    sf = get_pg_session()
    with sf.Session() as session:
        child = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.id == child_run_id)
            .one_or_none()
        )
        parent = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.id == parent_run_id)
            .one_or_none()
        )
        if child is None or parent is None:
            return
        # suspended/pending/running → keep waiting
        if child.status in ("pending", "running", "suspended"):
            return
        idem = f"{parent_run_id}:{parent_node_id}"
        row = (
            session.query(WorkflowRunNode)
            .filter(WorkflowRunNode.idempotency_key == idem)
            .one_or_none()
        )
        if row is None or row.status != "waiting_child":
            return

        outputs = _child_terminal_outputs(session, child)
        payload = {
            "child_run_id": child.id,
            "status": child.status,
            "outputs": outputs,
        }
        if child.status == "succeeded":
            _set_node_status(row, "succeeded")
            row.output_json = payload
            row.finished_at = datetime.utcnow()
            session.commit()
            schedule_resume_or_continue(parent_run_id)
            return

        # failed / cancelled → parent node failed (propagate)
        _set_node_status(row, "failed")
        row.output_json = payload
        row.error_message = f"child_{child.status}:{child.error_code or ''}"
        row.finished_at = datetime.utcnow()
        parent.status = "failed"
        parent.error_code = child.error_code or "CHILD_FAILED"
        parent.error_message = f"child {child.id} {child.status}"
        parent.finished_at = datetime.utcnow()
        session.commit()
        if parent.parent_run_id:
            wake_parent(
                parent.parent_run_id,
                parent.parent_node_id or "",
                child_run_id=parent.id,
            )


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


def _wake_parent_after_fail(run_id: str) -> None:
    sf = get_pg_session()
    with sf.Session() as session:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one_or_none()
        if run is None or not run.parent_run_id:
            return
        pid, pnode = run.parent_run_id, run.parent_node_id or ""
    wake_parent(pid, pnode, child_run_id=run_id)


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
        from backend.core.workflow.notify import resolve_hang_route
        from backend.modules.notification.service import (
            list_tenant_admin_user_ids,
            notify_many,
        )

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


def freeze_ir_snapshot(ir: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(ir)


def idempotency_key(run_id: str, node_id: str) -> str:
    return f"{run_id}:{node_id}"
