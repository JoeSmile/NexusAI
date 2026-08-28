"""Channel webhook stubs (Task 44.4) — signature-gated entry to Chat later.

STUB STATUS (评审 08-14 拍板 3A · 红线):
- Current gate = non-empty ``X-Channel-Signature`` only (NOT real HMAC).
- Real Feishu/WeCom signature verify + platform credentials are a **prerequisite**
  before enqueueing Chat DAG / claiming education-journey E2E closed.
- Gold line 8 uses API paths and bypasses this webhook.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from packages.channel.inbound import InboundMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/channels", tags=["channel-webhooks"])


def _parse_stub_body(platform: str, body: bytes) -> InboundMessage | None:
    """V1: JSON body with chat_id/text/sender; Feishu/WeCom adapters follow."""
    if not body:
        return None
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    chat_id = str(data.get("chat_id") or data.get("chatId") or "").strip()
    text = str(data.get("text") or data.get("content") or "").strip()
    sender = str(data.get("sender") or data.get("from") or "unknown").strip()
    if not chat_id or not text:
        return None
    return InboundMessage(
        platform=platform,
        chat_id=chat_id,
        sender=sender,
        text=text,
        attachments=list(data.get("attachments") or [])
        if isinstance(data.get("attachments"), list)
        else [],
        conversation_id=str(data.get("conversation_id") or "").strip(),
    )


@router.post("/{platform}/webhook")
async def channel_webhook(platform: str, request: Request) -> dict[str, Any]:
    """
    Stub: require non-empty X-Channel-Signature; parse inbound shape.
    Does **not** enqueue Chat DAG yet (``chat_queued: false``).
    """
    sig = request.headers.get("X-Channel-Signature") or request.headers.get(
        "x-channel-signature"
    )
    if not sig:
        raise HTTPException(status_code=401, detail={"code": "NO_SIGNATURE"})
    body = await request.body()
    msg = _parse_stub_body(platform, body)
    if msg is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_PAYLOAD", "message": "need chat_id and text"},
        )
    logger.info(
        "channel webhook stub platform=%s conversation_id=%s bytes=%s",
        platform,
        msg.conversation_id,
        len(body),
    )
    return {
        "accepted": True,
        "platform": platform,
        "conversation_id": msg.conversation_id,
        "stub": True,
        "signature_mode": "presence_only",
        "chat_queued": False,
    }
