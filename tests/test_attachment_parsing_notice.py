"""Task 76.2 — chat must say 正在解析 instead of waiting silently."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from packages.attachments.notice import parsing_notice_for_session
from packages.attachments.store import MemoryAttachmentStore, set_attachment_store
from packages.pipeline.nodes.preprocess import preprocess, should_gate_block
from packages.pipeline.state import make_initial_state


def test_parsing_notice_when_only_parsing_attachments() -> None:
    store = MemoryAttachmentStore()
    set_attachment_store(store)
    try:
        store.save(
            tenant_id="t1",
            session_id="s1",
            uploaded_by="u1",
            name="big.pdf",
            media_type="application/pdf",
            size=3_000_000,
            status="parsing",
            storage_path="/app/uploads/x",
            expired_at=datetime.now(UTC) + timedelta(days=7),
            blocks=[],
            attachment_id="a1",
        )
        msg = parsing_notice_for_session(tenant_id="t1", session_id="s1")
        assert msg is not None
        assert "解析" in msg
    finally:
        set_attachment_store(None)


def test_no_notice_when_ready() -> None:
    store = MemoryAttachmentStore()
    set_attachment_store(store)
    try:
        store.save(
            tenant_id="t1",
            session_id="s1",
            uploaded_by="u1",
            name="n.txt",
            media_type="text/plain",
            size=10,
            status="ready",
            storage_path="/app/uploads/x",
            expired_at=datetime.now(UTC) + timedelta(days=7),
            blocks=[],
            attachment_id="a1",
        )
        assert parsing_notice_for_session(tenant_id="t1", session_id="s1") is None
    finally:
        set_attachment_store(None)


@pytest.mark.asyncio
async def test_preprocess_short_circuits_while_parsing() -> None:
    store = MemoryAttachmentStore()
    set_attachment_store(store)
    try:
        store.save(
            tenant_id="t1",
            session_id="s1",
            uploaded_by="u1",
            name="big.pdf",
            media_type="application/pdf",
            size=3_000_000,
            status="parsing",
            storage_path="/app/uploads/x",
            expired_at=datetime.now(UTC) + timedelta(days=7),
            blocks=[],
            attachment_id="a1",
        )
        out = await preprocess(make_initial_state("t1", "u1", "s1", "总结一下"))
        assert "解析" in (out.get("response") or "")
        assert out.get("finish_reason") == "attachment_parsing"
        assert should_gate_block(out) == "end"
    finally:
        set_attachment_store(None)
