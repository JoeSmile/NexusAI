"""Task 44.4 — channel inbound protocol + webhook signature gate."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.modules.channel.inbound import InboundMessage
from backend.routers.channel_webhooks import router


def test_inbound_conversation_id_normalized() -> None:
    msg = InboundMessage(
        platform="feishu",
        chat_id="c1",
        sender="u1",
        text="热点口播",
    )
    assert msg.conversation_id == "feishu:c1"


def test_inbound_explicit_conversation_id() -> None:
    msg = InboundMessage(
        platform="wecom",
        chat_id="c1",
        sender="u1",
        text="hi",
        conversation_id="wecom:custom",
    )
    assert msg.conversation_id == "wecom:custom"


def test_webhook_rejects_missing_signature() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post(
        "/api/channels/feishu/webhook",
        json={"chat_id": "c1", "text": "hello", "sender": "u"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "NO_SIGNATURE"


def test_webhook_accepts_signed_payload() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.post(
        "/api/channels/feishu/webhook",
        headers={"X-Channel-Signature": "test-sig"},
        json={"chat_id": "oc_1", "text": "看看热点", "sender": "teacher"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert body["conversation_id"] == "feishu:oc_1"
    assert body["stub"] is True
