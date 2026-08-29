"""Parent/child wake logic — nested workflow completion propagation."""

from __future__ import annotations

import logging
from datetime import datetime

from packages.database.pgvector_session import WorkflowRun, WorkflowRunNode, get_pg_session
from packages.workflow.node_exec import _child_terminal_outputs
from packages.workflow.runner_shared import _set_node_status

logger = logging.getLogger(__name__)


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
            from packages.workflow.run_lifecycle import schedule_resume_or_continue

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


def _wake_parent_after_fail(run_id: str) -> None:
    sf = get_pg_session()
    with sf.Session() as session:
        run = session.query(WorkflowRun).filter(WorkflowRun.id == run_id).one_or_none()
        if run is None or not run.parent_run_id:
            return
        pid, pnode = run.parent_run_id, run.parent_node_id or ""
    wake_parent(pid, pnode, child_run_id=run_id)
