"""Auto-describe session images on upload (Task 76b.1)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from packages.attachments.describe import DescribeError, describe_image
from packages.attachments.store import get_attachment_store

logger = logging.getLogger(__name__)

DESCRIBE_UPLOAD_TIMEOUT_S = 60


def auto_describe_images_enabled() -> bool:
    raw = (os.getenv("ATTACH_AUTO_DESCRIBE_IMAGES") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def _is_image_media(media_type: str) -> bool:
    return str(media_type or "").startswith("image/")


async def maybe_describe_on_upload(
    *,
    tenant_id: str,
    user_id: str,
    session_id: str,
    attachment_id: str,
    media_type: str,
) -> str:
    """Return describe_status: ready | pending | skipped. Never raises to caller."""
    if not auto_describe_images_enabled() or not _is_image_media(media_type):
        return "skipped"
    store = get_attachment_store()
    try:
        result: dict[str, Any] = await asyncio.wait_for(
            describe_image(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                attachment_id=attachment_id,
            ),
            timeout=DESCRIBE_UPLOAD_TIMEOUT_S,
        )
    except DescribeError:
        store.mark_describe_pending(attachment_id, pending=True, increment=True)
        return "pending"
    except TimeoutError:
        logger.debug("image auto-describe timed out", exc_info=True)
        store.mark_describe_pending(attachment_id, pending=True, increment=True)
        return "pending"
    except Exception:
        logger.debug("image auto-describe failed", exc_info=True)
        store.mark_describe_pending(attachment_id, pending=True, increment=True)
        return "pending"

    text = str(result.get("text") or "").strip()
    if not text:
        store.mark_describe_pending(attachment_id, pending=True, increment=True)
        return "pending"
    store.append_caption(attachment_id, text)
    store.mark_describe_pending(attachment_id, pending=False, increment=False)
    return "ready"
