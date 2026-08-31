"""Task 76.3 — TTL 7d cascade delete attachments + disk files."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from packages.attachments.parse import AttachmentBlock
from packages.attachments.store import MemoryAttachmentStore, set_attachment_store
from packages.attachments.ttl import purge_expired_attachments
from packages.pipeline.session_attachments import session_has_ready_attachments


def test_purge_expired_removes_row_and_file(tmp_path: Path) -> None:
    store = MemoryAttachmentStore()
    set_attachment_store(store)
    try:
        path = tmp_path / "gone.pdf"
        path.write_bytes(b"%PDF")
        store.save(
            tenant_id="t1",
            session_id="s1",
            uploaded_by="u1",
            name="gone.pdf",
            media_type="application/pdf",
            size=4,
            status="ready",
            storage_path=str(path),
            expired_at=datetime.now(UTC) - timedelta(hours=1),
            blocks=[
                AttachmentBlock(
                    block_index=0, kind="page", text="old", char_count=3, page=1
                )
            ],
            attachment_id="exp1",
        )
        store.save(
            tenant_id="t1",
            session_id="s1",
            uploaded_by="u1",
            name="keep.pdf",
            media_type="application/pdf",
            size=4,
            status="ready",
            storage_path=str(tmp_path / "keep.pdf"),
            expired_at=datetime.now(UTC) + timedelta(days=3),
            blocks=[
                AttachmentBlock(
                    block_index=0, kind="page", text="keep", char_count=4, page=1
                )
            ],
            attachment_id="keep1",
        )
        n = purge_expired_attachments(now=datetime.now(UTC))
        assert n >= 1
        assert not path.exists()
        assert store.get(tenant_id="t1", session_id="s1", attachment_id="exp1") is None
        assert store.get(tenant_id="t1", session_id="s1", attachment_id="keep1") is not None
        assert session_has_ready_attachments("t1", "u1", "s1") is True
    finally:
        set_attachment_store(None)


def test_expired_only_session_stops_bypass() -> None:
    store = MemoryAttachmentStore()
    set_attachment_store(store)
    try:
        store.save(
            tenant_id="t1",
            session_id="s9",
            uploaded_by="u1",
            name="old.pdf",
            media_type="application/pdf",
            size=4,
            status="ready",
            storage_path="/tmp/old",
            expired_at=datetime.now(UTC) - timedelta(days=1),
            blocks=[],
            attachment_id="old1",
        )
        purge_expired_attachments(now=datetime.now(UTC))
        assert session_has_ready_attachments("t1", "u1", "s9") is False
    finally:
        set_attachment_store(None)
