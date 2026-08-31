"""Task 76.2 — file parse worker. Must share API ./uploads volume."""

from __future__ import annotations

import logging
import os
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("file_worker")

_POLL_SEC = float(os.environ.get("FILE_WORKER_POLL_SEC", "2.0"))


def process_once() -> bool:
    from packages.attachments.store import get_attachment_store
    from packages.attachments.worker import ParseJob, run_parse_job

    store = get_attachment_store()
    rows = store.list_parsing(limit=4)
    if not rows:
        return False
    for row in rows:
        job = ParseJob(
            attachment_id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            session_id=str(row["session_id"]),
            filename=str(row["name"]),
            storage_path=str(row["storage_path"]),
            attempts=int(row.get("parse_attempts") or 0),
        )
        result = run_parse_job(job)
        store.apply_parse_result(attachment_id=job.attachment_id, result=result)
        logger.info(
            "parsed attachment=%s status=%s reason=%s",
            job.attachment_id,
            result.status,
            result.reason,
        )
    return True


def run_forever() -> None:
    from apps.memory_worker.heartbeat import WorkerHeartbeat

    logger.info("file_worker starting poll=%ss", _POLL_SEC)
    hb = WorkerHeartbeat("file")
    hb.start()
    hb.beat()
    while True:
        hb.beat()
        try:
            did = process_once()
            if not did:
                time.sleep(_POLL_SEC)
        except Exception:
            logger.exception("file_worker loop error")
            time.sleep(_POLL_SEC)


if __name__ == "__main__":
    run_forever()
