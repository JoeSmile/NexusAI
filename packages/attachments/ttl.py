"""TTL cascade: delete expired attachments, blocks, and disk files."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_SCAN_INTERVAL_SEC = 300.0
_scanner_task: asyncio.Task[None] | None = None


def purge_expired_attachments(*, now: datetime | None = None) -> int:
    from packages.attachments.store import get_attachment_store

    when = now or datetime.now(UTC)
    store = get_attachment_store()
    rows = store.list_expired(now=when)
    n = 0
    for row in rows:
        path = str(row.get("storage_path") or "")
        store.delete(attachment_id=str(row["id"]))
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                logger.debug("unlink expired attachment failed path=%s", path, exc_info=True)
        n += 1
    return n


async def _scan_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_SCAN_INTERVAL_SEC)
            purge_expired_attachments()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("attachment ttl scan error", exc_info=True)


def start_attachment_ttl_scanner() -> None:
    global _scanner_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _scanner_task is not None and not _scanner_task.done():
        return
    _scanner_task = loop.create_task(_scan_loop(), name="attachment-ttl-scanner")
