"""Workflow node execution — IR ready-driven loop and per-node handlers.

Patch note: ``invoke`` / ``get_capability_registry`` are bound in this module;
mock ``packages.workflow.node_exec.invoke`` (etc.), not only ``runner.*``.
See ``runner`` module docstring.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.core.errors import ErrorCode, NexusAIException
from backend.core.guardrails.input_guard import detect_injection_in_params
from backend.core.org.scope import OrgScope, resolve_org_scope
from backend.database.pgvector_session import Workflow, WorkflowRun, WorkflowRunNode
from packages.auth.models import TenantContext
from packages.capability.errors import CapabilityNotFoundError
from packages.capability.invoke import invoke
from packages.capability.registry import get_capability_registry
from packages.workflow.composition import (
    CompositionDepthExceeded,
    check_composition_budget,
)
from packages.workflow.evidence import evidence_from_rag_sources, node_output
from packages.workflow.grants import (
    create_pending_request,
    expire_stale_approvals_for_node,
    find_active_grant_covering,
    grant_auth_context,
    is_eligible_approver,
    issue_auto_grant,
)
from packages.workflow.ir import WorkflowIR, validate_params_against_spec
from packages.workflow.run_state import assert_transition
from packages.workflow.runner_shared import (
    RunSuspended,
    RunWaitingChild,
    _audit,
    _collect_outputs,
    _fail_node_ref,
    _http_depth_exceeded,
    _load_node_statuses,
    _mark_node_skipped,
    _run_inputs_from_context,
    _set_node_status,
)
from packages.workflow.security_gates import HangGateError, assert_hang_wait_allowed
from packages.workflow.service import capability_catalog_visible

logger = logging.getLogger(__name__)


async def _execute_ir_ready_driven(
    session: Session,
    *,
    run: WorkflowRun,
    ir: WorkflowIR,
    tenant: TenantContext,
    org_scope: OrgScope,
) -> None:
    """R-C: serially execute ready nodes (preds succeeded/skipped); empty edges → IR order."""
    from packages.workflow.dataflow import (
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
                from packages.workflow.notify import notify_hang_pending

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
        # G7: script.gen / 口播类出口脱敏（fail-open）
        if cap_id in ("script.gen", "content.script_gen") or str(
            done_meta.get("op") or ""
        ) in ("script.gen", "content.script_gen"):
            try:
                from backend.core.memory_service import redact_student_names_in_text

                names = params.get("student_names")
                if isinstance(names, str):
                    names = [names]
                if not isinstance(names, list):
                    names = None
                warm = params.get("warm") if isinstance(params.get("warm"), dict) else None
                before = answer
                answer = redact_student_names_in_text(
                    answer,
                    tenant_id=run.tenant_id,
                    names=names,
                    warm=warm,
                )
                if answer != before:
                    done_meta = dict(done_meta)
                    done_meta["student_pii_redacted"] = True
                    if isinstance(done_meta.get("result"), dict):
                        done_meta["result"] = dict(done_meta["result"])
                        done_meta["result"]["script"] = answer
                        done_meta["result"]["student_pii_redacted"] = True
            except Exception:
                logger.debug("runner G7 redaction skipped", exc_info=True)
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


async def _execute_workflow_node(
    session: Session,
    *,
    run: WorkflowRun,
    node: dict[str, Any],
    tenant: TenantContext,
    org_scope: OrgScope,
) -> None:
    """kind=workflow → nested start_run; parent node → waiting_child."""
    from packages.workflow.run_lifecycle import schedule_execute, start_run

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
