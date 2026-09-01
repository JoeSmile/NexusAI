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
            "parse_attempts": 0,
            "describe_pending": False,
            "describe_attempts": 0,
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

    def append_caption(self, attachment_id: str, text: str) -> None:
        row = self.items.get(attachment_id)
        if row is None:
            return
        body = (text or "").strip()
        if not body:
            return
        blocks = list(row.get("blocks") or [])
        nxt = max((int(b.get("block_index") or 0) for b in blocks), default=-1) + 1
        blocks.append(
            {
                "block_index": nxt,
                "kind": "caption",
                "text": body,
                "char_count": len(body),
                "page": None,
                "sheet": None,
                "rows": None,
            }
        )
        row["blocks"] = blocks
        row["describe_pending"] = False

    def mark_describe_pending(
        self,
        attachment_id: str,
        *,
        pending: bool,
        increment: bool = False,
    ) -> None:
        row = self.items.get(attachment_id)
        if row is None:
            return
        row["describe_pending"] = bool(pending)
        if increment:
            row["describe_attempts"] = int(row.get("describe_attempts") or 0) + 1

    def list_session(self, *, tenant_id: str, session_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.items.values()
            if row["tenant_id"] == tenant_id and row["session_id"] == session_id
        ]

    def list_parsing(self, *, limit: int = 8) -> list[dict[str, Any]]:
        out = [dict(row) for row in self.items.values() if row["status"] == "parsing"]
        return out[:limit]

    def apply_parse_result(self, *, attachment_id: str, result: Any) -> None:
        row = self.items.get(attachment_id)
        if row is None:
            return
        row["parse_attempts"] = int(getattr(result, "attempts", 0) or 0)
        if result.status == "ready":
            row["status"] = "ready"
            row["blocks"] = [
                {
                    "block_index": b.block_index,
                    "kind": b.kind,
                    "text": b.text,
                    "char_count": b.char_count,
                    "page": b.page,
                    "sheet": b.sheet,
                    "rows": b.rows,
                }
                for b in (result.blocks or [])
            ]
            return
        if result.status == "ocr_required":
            row["status"] = "ocr_required"
            row["blocks"] = []
            return
        if not getattr(result, "should_retry", False):
            row["status"] = "failed"
            return
        row["status"] = "parsing"

    def list_expired(self, *, now: datetime) -> list[dict[str, Any]]:
        from packages.attachments.notice import row_is_live

        return [
            dict(row)
            for row in self.items.values()
            if not row_is_live(row, now=now)
        ]

    def delete(self, *, attachment_id: str) -> dict[str, Any] | None:
        return self.items.pop(attachment_id, None)


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
                    parse_attempts=0,
                    describe_pending=False,
                    describe_attempts=0,
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
                "parse_attempts": int(getattr(row, "parse_attempts", 0) or 0),
                "describe_pending": bool(getattr(row, "describe_pending", False)),
                "describe_attempts": int(getattr(row, "describe_attempts", 0) or 0),
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

    def list_session(self, *, tenant_id: str, session_id: str) -> list[dict[str, Any]]:
        from packages.database.pgvector_session import Attachment, get_pg_session

        sf = get_pg_session()
        with sf.Session() as session:
            rows = (
                session.query(Attachment)
                .filter(
                    Attachment.tenant_id == tenant_id,
                    Attachment.session_id == session_id,
                )
                .all()
            )
            return [_attachment_row(r) for r in rows]

    def list_parsing(self, *, limit: int = 8) -> list[dict[str, Any]]:
        from packages.database.pgvector_session import Attachment, get_pg_session

        sf = get_pg_session()
        with sf.Session() as session:
            rows = (
                session.query(Attachment)
                .filter(Attachment.status == "parsing")
                .limit(limit)
                .all()
            )
            return [_attachment_row(r) for r in rows]

    def apply_parse_result(self, *, attachment_id: str, result: Any) -> None:
        from packages.database.pgvector_session import Attachment, AttachmentBlock, get_pg_session

        sf = get_pg_session()
        with sf.Session() as session:
            row = session.query(Attachment).filter(Attachment.id == attachment_id).first()
            if row is None:
                return
            row.parse_attempts = int(getattr(result, "attempts", 0) or 0)
            if result.status == "ready":
                row.status = "ready"
                session.query(AttachmentBlock).filter(
                    AttachmentBlock.attachment_id == attachment_id
                ).delete()
                for b in result.blocks or []:
                    session.add(
                        AttachmentBlock(
                            attachment_id=attachment_id,
                            tenant_id=row.tenant_id,
                            session_id=row.session_id,
                            block_index=b.block_index,
                            kind=b.kind,
                            page=b.page,
                            sheet=b.sheet,
                            rows=b.rows,
                            text=b.text,
                            char_count=b.char_count,
                        )
                    )
            elif result.status == "ocr_required":
                row.status = "ocr_required"
            elif not getattr(result, "should_retry", False):
                row.status = "failed"
            else:
                row.status = "parsing"
            session.commit()

    def append_caption(self, attachment_id: str, text: str) -> None:
        from packages.database.pgvector_session import Attachment, AttachmentBlock, get_pg_session

        body = (text or "").strip()
        if not body:
            return
        sf = get_pg_session()
        with sf.Session() as session:
            row = session.query(Attachment).filter(Attachment.id == attachment_id).first()
            if row is None:
                return
            nxt = (
                session.query(AttachmentBlock.block_index)
                .filter(AttachmentBlock.attachment_id == attachment_id)
                .order_by(AttachmentBlock.block_index.desc())
                .first()
            )
            idx = int(nxt[0]) + 1 if nxt else 0
            session.add(
                AttachmentBlock(
                    attachment_id=attachment_id,
                    tenant_id=row.tenant_id,
                    session_id=row.session_id,
                    block_index=idx,
                    kind="caption",
                    page=None,
                    sheet=None,
                    rows=None,
                    text=body,
                    char_count=len(body),
                )
            )
            if hasattr(row, "describe_pending"):
                row.describe_pending = False
            session.commit()

    def mark_describe_pending(
        self,
        attachment_id: str,
        *,
        pending: bool,
        increment: bool = False,
    ) -> None:
        from packages.database.pgvector_session import Attachment, get_pg_session

        sf = get_pg_session()
        with sf.Session() as session:
            row = session.query(Attachment).filter(Attachment.id == attachment_id).first()
            if row is None:
                return
            if hasattr(row, "describe_pending"):
                row.describe_pending = bool(pending)
            if increment and hasattr(row, "describe_attempts"):
                row.describe_attempts = int(getattr(row, "describe_attempts", 0) or 0) + 1
            session.commit()

    def list_expired(self, *, now: datetime) -> list[dict[str, Any]]:
        from packages.database.pgvector_session import Attachment, get_pg_session

        sf = get_pg_session()
        with sf.Session() as session:
            rows = session.query(Attachment).filter(Attachment.expired_at <= now).all()
            return [_attachment_row(r) for r in rows]

    def delete(self, *, attachment_id: str) -> dict[str, Any] | None:
        from packages.database.pgvector_session import Attachment, get_pg_session

        sf = get_pg_session()
        with sf.Session() as session:
            row = session.query(Attachment).filter(Attachment.id == attachment_id).first()
            if row is None:
                return None
            payload = _attachment_row(row)
            session.delete(row)
            session.commit()
            return payload


def _attachment_row(row: Any) -> dict[str, Any]:
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
        "parse_attempts": int(getattr(row, "parse_attempts", 0) or 0),
        "describe_pending": bool(getattr(row, "describe_pending", False)),
        "describe_attempts": int(getattr(row, "describe_attempts", 0) or 0),
        "expired_at": row.expired_at,
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
