"""Shared helpers, constants, and exceptions for workflow runner submodules.

Patch note: ``write_audit_sync`` is imported here; consumers of ``_audit`` that
need to mock audit writes should patch
``packages.workflow.runner_shared.write_audit_sync``.
Names re-exported into ``run_lifecycle`` must be patched on ``run_lifecycle``.
See ``runner`` module docstring.
"""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.audit import write_audit_sync
from packages.errors import ErrorCode
from packages.org.scope import OrgScope, resolve_org_scope
from backend.database.pgvector_session import WorkflowRun, WorkflowRunNode, get_pg_session
from packages.auth.models import TenantContext
from packages.workflow.composition import CompositionDepthExceeded
from packages.workflow.ir import WorkflowIR
from packages.workflow.run_state import assert_node_transition

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
    from packages.auth.session_auth import _load_extra_permissions

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


def _notify_run_done(run: WorkflowRun, *, status: str) -> None:
    try:
        from packages.notification.service import notify_run_terminal

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


def freeze_ir_snapshot(ir: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(ir)


def idempotency_key(run_id: str, node_id: str) -> str:
    return f"{run_id}:{node_id}"
