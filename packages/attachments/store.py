"""Attachment persistence (PG in prod; memory store for tests)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from packages.attachments.parse import AttachmentBlock as ParsedBlock

SYNC_MAX_BYTES = 2 * 1024 * 1024


class AttachmentForbidden(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class MemoryAttachmentStore:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def save(
        self,
        *,
        tenant_id: str,
        session_id: str,
        uploaded_by: str,
        name: str,
        media_type: str,
        size: int,
        status: str,
        storage_path: str,
        attachment_id: str | None = None,
        expired_at: datetime,
        blocks: list[ParsedBlock],
    ) -> str:
        aid = attachment_id or uuid.uuid4().hex
        self.items[aid] = {
            "id": aid,
            "tenant_id": tenant_id,
            "session_id": session_id,
            "uploaded_by": uploaded_by,
            "name": name,
            "media_type": media_type,
            "size": size,
            "status": status,
            "storage_path": storage_path,
            "expired_at": expired_at,
            "blocks": [
                {
                    "block_index": b.block_index,
                    "kind": b.kind,
                    "text": b.text,
                    "char_count": b.char_count,
                    "page": b.page,
                    "sheet": b.sheet,
                    "rows": b.rows,
                }
                for b in blocks
            ],
        }
        return aid

    def get(
        self,
        *,
        tenant_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        row = self.items.get(attachment_id)
        if row is None:
            return None
        if row["tenant_id"] != tenant_id:
            raise AttachmentForbidden("cross_tenant")
        if row["session_id"] != session_id:
            raise AttachmentForbidden("cross_session")
        return row


class PgAttachmentStore:
    def save(
        self,
        *,
        tenant_id: str,
        session_id: str,
        uploaded_by: str,
        name: str,
        media_type: str,
        size: int,
        status: str,
        storage_path: str,
        attachment_id: str | None = None,
        expired_at: datetime,
        blocks: list[ParsedBlock],
    ) -> str:
        from packages.database.pgvector_session import Attachment, AttachmentBlock, get_pg_session

        aid = attachment_id or uuid.uuid4().hex
        sf = get_pg_session()
        with sf.Session() as session:
            session.add(
                Attachment(
                    id=aid,
                    tenant_id=tenant_id,
                    session_id=session_id,
                    uploaded_by=uploaded_by,
                    name=name,
                    media_type=media_type,
                    size=size,
                    status=status,
                    storage_path=storage_path,
                    expired_at=expired_at,
                )
            )
            for b in blocks:
                session.add(
                    AttachmentBlock(
                        attachment_id=aid,
                        tenant_id=tenant_id,
                        session_id=session_id,
                        block_index=b.block_index,
                        kind=b.kind,
                        page=b.page,
                        sheet=b.sheet,
                        rows=b.rows,
                        text=b.text,
                        char_count=b.char_count,
                    )
                )
            session.commit()
        return aid

    def get(
        self,
        *,
        tenant_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        from packages.database.pgvector_session import Attachment, AttachmentBlock, get_pg_session

        sf = get_pg_session()
        with sf.Session() as session:
            row = (
                session.query(Attachment)
                .filter(Attachment.id == attachment_id)
                .first()
            )
            if row is None:
                return None
            if row.tenant_id != tenant_id:
                raise AttachmentForbidden("cross_tenant")
            if row.session_id != session_id:
                raise AttachmentForbidden("cross_session")
            blocks = (
                session.query(AttachmentBlock)
                .filter(AttachmentBlock.attachment_id == attachment_id)
                .order_by(AttachmentBlock.block_index)
                .all()
            )
            return {
                "id": row.id,
                "tenant_id": row.tenant_id,
                "session_id": row.session_id,
                "uploaded_by": row.uploaded_by,
                "name": row.name,
                "media_type": row.media_type,
                "size": row.size,
                "status": row.status,
                "storage_path": row.storage_path,
                "expired_at": row.expired_at,
                "blocks": [
                    {
                        "block_index": b.block_index,
                        "kind": b.kind,
                        "text": b.text,
                        "char_count": b.char_count,
                        "page": b.page,
                        "sheet": b.sheet,
                        "rows": b.rows,
                    }
                    for b in blocks
                ],
            }


_STORE: MemoryAttachmentStore | PgAttachmentStore | None = None


def get_attachment_store() -> MemoryAttachmentStore | PgAttachmentStore:
    global _STORE
    if _STORE is None:
        _STORE = PgAttachmentStore()
    return _STORE


def set_attachment_store(
    store: MemoryAttachmentStore | PgAttachmentStore | None,
) -> None:
    global _STORE
    _STORE = store
