"""Ingest chat attachments: validate + parse (sync) or mark parsing."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from packages.attachments.parse import parse_document
from packages.attachments.store import (
    SYNC_MAX_BYTES,
    get_attachment_store,
)
from packages.attachments.validate import validate_attachment_bytes


def ingest_bytes(
    *,
    tenant_id: str,
    user_id: str,
    session_id: str,
    filename: str,
    data: bytes,
    storage_path: str,
    expired_at: datetime,
    attachment_id: str | None = None,
) -> dict[str, Any]:
    kind = validate_attachment_bytes(filename=filename, data=data)
    store = get_attachment_store()
    if len(data) > SYNC_MAX_BYTES:
        media = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "csv": "text/csv",
            "txt": "text/plain",
        }.get(kind, "application/octet-stream")
        aid = store.save(
            tenant_id=tenant_id,
            session_id=session_id,
            uploaded_by=user_id,
            name=filename,
            media_type=media,
            size=len(data),
            status="parsing",
            storage_path=storage_path,
            expired_at=expired_at,
            blocks=[],
            attachment_id=attachment_id,
        )
        return {
            "attachment_id": aid,
            "status": "parsing",
            "name": filename,
            "blocks": [],
        }

    parsed = parse_document(data, filename)
    aid = store.save(
        tenant_id=tenant_id,
        session_id=session_id,
        uploaded_by=user_id,
        name=filename,
        media_type=parsed.media_type,
        size=len(data),
        status=parsed.status,
        storage_path=storage_path,
        expired_at=expired_at,
        blocks=parsed.blocks,
        attachment_id=attachment_id,
    )
    return {
        "attachment_id": aid,
        "status": parsed.status,
        "name": filename,
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
            for b in parsed.blocks
        ],
    }
