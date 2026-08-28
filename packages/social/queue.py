"""social_tasks SKIP LOCKED claim + stale reclaim (Task 52 S2)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.database.pgvector_session import SocialTask

logger = logging.getLogger(__name__)

STALE_RUNNING_MINUTES = 30


def reclaim_stale_running(
    session: Session,
    *,
    older_than_minutes: int = STALE_RUNNING_MINUTES,
    now: datetime | None = None,
) -> int:
    """Reset long-running tasks back to pending (crash recovery)."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(minutes=older_than_minutes)
    result = session.execute(
        text(
            """
            UPDATE social_tasks
            SET status = 'pending',
                leased_at = NULL,
                error = CASE
                  WHEN error IS NULL OR error = '' THEN '[reclaimed_stale]'
                  ELSE error || ' [reclaimed_stale]'
                END
            WHERE status = 'running'
              AND leased_at IS NOT NULL
              AND leased_at < :cutoff
            """
        ),
        {"cutoff": cutoff},
    )
    return int(result.rowcount or 0)


def claim_next_task(session: Session) -> SocialTask | None:
    """Claim one pending task with FOR UPDATE SKIP LOCKED → running."""
    row = session.execute(
        text(
            """
            SELECT id FROM social_tasks
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        )
    ).fetchone()
    if row is None:
        return None
    task_id = int(row[0])
    task = session.query(SocialTask).filter(SocialTask.id == task_id).one()
    task.status = "running"
    task.leased_at = datetime.now(UTC)
    task.progress = max(task.progress or 0, 5)
    session.flush()
    return task


def find_active_task(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
) -> SocialTask | None:
    return (
        session.query(SocialTask)
        .filter(
            SocialTask.tenant_id == tenant_id,
            SocialTask.user_id == user_id,
            SocialTask.status.in_(("pending", "running")),
        )
        .order_by(SocialTask.id.desc())
        .first()
    )


def mark_task(
    session: Session,
    task: SocialTask,
    *,
    status: str | None = None,
    progress: int | None = None,
    total_count: int | None = None,
    new_count: int | None = None,
    skipped: int | None = None,
    error: str | None = None,
    retry_count: int | None = None,
    clear_lease: bool = False,
    finish: bool = False,
) -> None:
    if status is not None:
        task.status = status
    if progress is not None:
        task.progress = progress
    if total_count is not None:
        task.total_count = total_count
    if new_count is not None:
        task.new_count = new_count
    if skipped is not None:
        task.skipped = skipped
    if error is not None:
        task.error = error
    if retry_count is not None:
        task.retry_count = retry_count
    if clear_lease:
        task.leased_at = None
    if finish:
        task.finished_at = datetime.now(UTC)
    session.flush()
    # Commit so API poll (other connection) can see progress / partial results.
    session.commit()
