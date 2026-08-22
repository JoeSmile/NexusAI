"""Image input guardrails — hash + size; NSFW/OCR hooks (Task 58 slice 1)."""

from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)


def image_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def check_image_input(
    *,
    content: bytes,
    filename: str,
    content_type: str,
) -> tuple[bool, str, str]:
    """Validate image for pipeline entry. Returns (ok, error_code, image_hash)."""
    if not content:
        return False, "FILE_002", ""
    if len(content) > 10 * 1024 * 1024:
        return False, "FILE_001", ""
    digest = image_content_hash(content)
    # Phase 2: NSFW / OCR sensitive — placeholder only
    logger.debug(
        "image_guard_pass filename=%s ctype=%s bytes=%s hash=%s",
        filename,
        content_type,
        len(content),
        digest[:12],
    )
    return True, "", digest
