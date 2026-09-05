"""Task 83.3 — knowledge ingest worker. Must share API ./uploads volume."""

from __future__ import annotations

import logging
import os
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("knowledge_worker")

_POLL_SEC = float(os.environ.get("KNOWLEDGE_WORKER_POLL_SEC", "2.0"))
# parse+embed a large PDF can exceed the 120s default used by short-task workers.
_STALL_SEC = float(os.environ.get("KNOWLEDGE_WORKER_STALL_SEC", "1800"))


def process_once(*, on_progress=None) -> bool:
    from packages.rag.ingest import process_one

    return process_one(on_progress=on_progress)


def run_forever() -> None:
    from apps.memory_worker.heartbeat import WorkerHeartbeat

    logger.info(
        "knowledge_worker starting poll=%ss stall=%ss", _POLL_SEC, _STALL_SEC
    )
    hb = WorkerHeartbeat("knowledge", stall_timeout=_STALL_SEC)
    hb.start()
    hb.beat()
    while True:
        hb.beat()
        try:
            did = process_once(on_progress=hb.beat)
            if not did:
                time.sleep(_POLL_SEC)
        except Exception:
            logger.exception("knowledge_worker loop error")
            time.sleep(_POLL_SEC)


if __name__ == "__main__":
    run_forever()
