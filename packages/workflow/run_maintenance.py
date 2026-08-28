"""Startup maintenance — zombie run cleanup."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from packages.errors import ErrorCode
from backend.database.pgvector_session import WorkflowRun, WorkflowRunNode, get_pg_session
from packages.workflow.runner_shared import _audit


def mark_zombie_runs_failed() -> int:
    """Startup: leftover running → failed + audit; exempt waiting_child parents.

    G6：advisory lock 防多副本双清。
    """
    sf = get_pg_session()
    n = 0
    with sf.Session() as session:
        locked = session.execute(
            text("SELECT pg_try_advisory_lock(:k)"),
            {"k": 41030606},
        ).scalar()
        if not locked:
            return 0
        try:
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
        finally:
            session.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": 41030606}
            )
    return n
