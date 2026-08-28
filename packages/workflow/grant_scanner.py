"""E3.2 / E3.3 — grant auto_renew + expiring scan（进程内 + DB 租约）。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_SCAN_INTERVAL_SEC = 60.0
_scanner_task: asyncio.Task[None] | None = None


def scan_once() -> dict[str, Any]:
    from packages.workflow.grants import scan_grants_for_auto_renew

    result: dict[str, Any] = dict(scan_grants_for_auto_renew())
    try:
        from packages.workflow.grant_notify import scan_expiring_grants

        result["notify"] = scan_expiring_grants()
    except Exception:
        logger.debug("expiring notify scan skipped", exc_info=True)
        result["notify"] = {}
    try:
        from packages.workflow.subscription import scan_subscription_expiring

        result["subscription"] = scan_subscription_expiring()
    except Exception:
        logger.debug("subscription scan skipped", exc_info=True)
        result["subscription"] = {}
    return result


async def _scan_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_SCAN_INTERVAL_SEC)
            scan_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("grant scan loop error", exc_info=True)


def start_grant_scanner() -> None:
    global _scanner_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _scanner_task is not None and not _scanner_task.done():
        return
    _scanner_task = loop.create_task(_scan_loop(), name="grant-auto-renew-scanner")


def stop_grant_scanner() -> None:
    global _scanner_task
    if _scanner_task is not None and not _scanner_task.done():
        _scanner_task.cancel()
    _scanner_task = None
