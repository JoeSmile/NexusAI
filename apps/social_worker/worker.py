"""Task 52 S2 — social analysis worker (SKIP LOCKED claim loop)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("social_worker")

_POLL_SEC = float(os.environ.get("SOCIAL_WORKER_POLL_SEC", "2.0"))


def _session_factory() -> Any:
    from backend.database.pgvector_session import PGVectorSession

    return PGVectorSession().Session


def process_once(session_factory: Callable[[], Any] | None = None) -> bool:
    """Claim and process one task. Returns True if work was done."""
    from backend.core.social.pipeline import process_task
    from backend.core.social.queue import claim_next_task, reclaim_stale_running
    from backend.database.pgvector_session import SocialTask

    Session = session_factory or _session_factory()
    with Session() as session:
        reclaim_stale_running(session)
        session.commit()

    with Session() as session:
        task = claim_next_task(session)
        if task is None:
            session.commit()
            return False
        task_id = int(task.id)
        session.commit()

    with Session() as session:
        task = session.query(SocialTask).filter(SocialTask.id == task_id).one()
        logger.info(
            "processing social task id=%s tenant=%s platform=%s",
            task.id,
            task.tenant_id,
            task.platform,
        )
        process_task(session, task)
    return True


def run_forever() -> None:
    from apps.memory_worker.heartbeat import WorkerHeartbeat

    logger.info("social_worker starting poll=%ss", _POLL_SEC)
    hb = WorkerHeartbeat("social")
    hb.start()
    hb.beat()  # first beat before the loop
    while True:
        hb.beat()  # liveness progress (watchdog + Redis heartbeat)
        try:
            did = process_once()
            if not did:
                time.sleep(_POLL_SEC)
        except Exception:
            logger.exception("social_worker loop error")
            time.sleep(_POLL_SEC)


if __name__ == "__main__":
    run_forever()
