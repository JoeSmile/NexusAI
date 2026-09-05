"""Async RAG PDF ingest: persist file, queue knowledge_documents, worker pipeline.

Task 83 — API returns 202 immediately; apps.knowledge_worker claims queued rows.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.database.pgvector_session import (
    KnowledgeChunk,
    KnowledgeDocument,
    get_pg_session,
)
from packages.errors import ErrorCode, NexusAIException

logger = logging.getLogger(__name__)

WRITE_CHUNK = 1024 * 1024
IN_FLIGHT = frozenset({"queued", "parsing", "chunking", "embedding"})
STALE_MINUTES = 120
_PROGRESS = {
    "queued": 0.0,
    "parsing": 0.15,
    "chunking": 0.35,
    "embedding": 0.55,
    "ready": 1.0,
    "failed": 0.0,
}


@dataclass
class IngestAck:
    doc_id: str
    filename: str
    status: str
    duplicate: bool
    file_hash: str
    storage_path: str


def uploads_root() -> Path:
    raw = (os.getenv("UPLOADS_DIR") or os.getenv("UPLOAD_DIR") or "./uploads").strip()
    return Path(raw).expanduser()


def _safe_tenant(tenant_id: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "_" for c in tenant_id)
    return cleaned or "default"


def knowledge_dir(tenant_id: str) -> Path:
    return uploads_root() / "knowledge" / _safe_tenant(tenant_id)


def task_progress(row: KnowledgeDocument) -> float:
    if row.status == "embedding" and (row.chunk_count or 0) > 0:
        frac = (row.chunks_so_far or 0) / max(row.chunk_count, 1)
        return min(0.95, 0.55 + 0.4 * frac)
    return float(_PROGRESS.get(row.status or "", 0.0))


def page_no_from_meta(meta: dict | None) -> int | None:
    if not meta:
        return None
    page_no = meta.get("page_no")
    if isinstance(page_no, int):
        return page_no
    page = meta.get("page")
    if isinstance(page, int):
        return page + 1 if page >= 0 else page
    if isinstance(page, str) and page.isdigit():
        return int(page) + 1
    return None


def _now() -> datetime:
    return datetime.utcnow()


def _find_by_hash(session: Session, tenant_id: str, file_hash: str) -> KnowledgeDocument | None:
    return (
        session.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.tenant_id == tenant_id,
            KnowledgeDocument.file_hash == file_hash,
        )
        .one_or_none()
    )


def _ack_from_row(row: KnowledgeDocument, *, duplicate: bool) -> IngestAck:
    return IngestAck(
        doc_id=str(row.id),
        filename=str(row.filename),
        status=str(row.status),
        duplicate=duplicate,
        file_hash=str(row.file_hash),
        storage_path=str(row.storage_path or ""),
    )


def _write_stream(dest_part: Path, chunks: Iterator[bytes]) -> tuple[str, bytes]:
    hasher = hashlib.sha256()
    head = b""
    dest_part.parent.mkdir(parents=True, exist_ok=True)
    with dest_part.open("wb") as fh:
        for part in chunks:
            if not part:
                continue
            if len(head) < 5:
                need = 5 - len(head)
                head += part[:need]
            hasher.update(part)
            fh.write(part)
    return hasher.hexdigest(), head


def _finalize_new_row(
    *,
    tenant_id: str,
    org_unit_id: str | None,
    filename: str,
    file_hash: str,
    storage_path: str,
) -> IngestAck:
    doc_id = str(uuid.uuid4())
    label = (filename or "document.pdf").strip()[:256] or "document.pdf"
    sf = get_pg_session()
    with sf.Session() as session:
        existing = _find_by_hash(session, tenant_id, file_hash)
        if existing is not None:
            Path(storage_path).unlink(missing_ok=True)
            return _ack_from_row(existing, duplicate=True)
        row = KnowledgeDocument(
            id=doc_id,
            tenant_id=tenant_id,
            org_unit_id=org_unit_id,
            filename=label,
            storage_path=storage_path,
            file_hash=file_hash,
            status="queued",
            chunk_count=0,
            chunks_so_far=0,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            Path(storage_path).unlink(missing_ok=True)
            again = _find_by_hash(session, tenant_id, file_hash)
            if again is None:
                raise
            return _ack_from_row(again, duplicate=True)
        session.refresh(row)
        return _ack_from_row(row, duplicate=False)


def enqueue_pdf_bytes(
    *,
    tenant_id: str,
    org_unit_id: str | None,
    filename: str,
    data: bytes,
) -> IngestAck:
    def _gen() -> Iterator[bytes]:
        if not data:
            return
        for i in range(0, len(data), WRITE_CHUNK):
            yield data[i : i + WRITE_CHUNK]

    return enqueue_pdf_chunks(
        tenant_id=tenant_id,
        org_unit_id=org_unit_id,
        filename=filename,
        chunks=_gen(),
    )


def enqueue_pdf_chunks(
    *,
    tenant_id: str,
    org_unit_id: str | None,
    filename: str,
    chunks: Iterator[bytes],
) -> IngestAck:
    dest_dir = knowledge_dir(tenant_id)
    dest_part = dest_dir / f"{uuid.uuid4().hex}.part"
    try:
        file_hash, head = _write_stream(dest_part, chunks)
        if dest_part.stat().st_size <= 0:
            dest_part.unlink(missing_ok=True)
            raise NexusAIException(ErrorCode.FILE_INVALID_TYPE.value, "empty_pdf")
        if not head.startswith(b"%PDF"):
            dest_part.unlink(missing_ok=True)
            raise NexusAIException(ErrorCode.FILE_INVALID_TYPE.value, "not_a_pdf")
        final_path = dest_dir / f"{uuid.uuid4().hex}.pdf"
        dest_part.replace(final_path)
        return _finalize_new_row(
            tenant_id=tenant_id,
            org_unit_id=org_unit_id,
            filename=filename,
            file_hash=file_hash,
            storage_path=str(final_path),
        )
    except Exception:
        dest_part.unlink(missing_ok=True)
        raise


async def enqueue_pdf_upload(
    *,
    tenant_id: str,
    org_unit_id: str | None,
    filename: str,
    read_chunk,
) -> IngestAck:
    """Stream an UploadFile-like reader to disk (1MB chunks), then enqueue."""

    async def _aiter() -> AsyncIterator[bytes]:
        while True:
            part = await read_chunk(WRITE_CHUNK)
            if not part:
                break
            yield part

    dest_dir = knowledge_dir(tenant_id)
    dest_part = dest_dir / f"{uuid.uuid4().hex}.part"
    hasher = hashlib.sha256()
    head = b""
    dest_part.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest_part.open("wb") as fh:
            async for part in _aiter():
                if len(head) < 5:
                    need = 5 - len(head)
                    head += part[:need]
                hasher.update(part)
                fh.write(part)
        if dest_part.stat().st_size <= 0:
            dest_part.unlink(missing_ok=True)
            raise NexusAIException(ErrorCode.FILE_INVALID_TYPE.value, "empty_pdf")
        if not head.startswith(b"%PDF"):
            dest_part.unlink(missing_ok=True)
            raise NexusAIException(ErrorCode.FILE_INVALID_TYPE.value, "not_a_pdf")
        final_path = dest_dir / f"{uuid.uuid4().hex}.pdf"
        dest_part.replace(final_path)
        return _finalize_new_row(
            tenant_id=tenant_id,
            org_unit_id=org_unit_id,
            filename=filename,
            file_hash=hasher.hexdigest(),
            storage_path=str(final_path),
        )
    except Exception:
        dest_part.unlink(missing_ok=True)
        raise


def ingest_ack_body(ack: IngestAck) -> dict:
    msg = "文件已存在" if ack.duplicate else "已排队解析"
    doc = {
        "doc_id": ack.doc_id,
        "filename": ack.filename,
        "status": ack.status,
        "duplicate": ack.duplicate,
    }
    return {
        "success": True,
        "message": msg,
        "task_ids": [ack.doc_id],
        "documents": [doc],
        "data": doc,
    }


def get_task(tenant_id: str, task_id: str) -> KnowledgeDocument | None:
    sf = get_pg_session()
    with sf.Session() as session:
        row = session.get(KnowledgeDocument, task_id)
        if row is None or str(row.tenant_id) != tenant_id:
            return None
        session.expunge(row)
        return row


def task_payload(row: KnowledgeDocument) -> dict:
    return {
        "task_id": row.id,
        "doc_id": row.id,
        "filename": row.filename,
        "status": row.status,
        "progress": task_progress(row),
        "chunks_so_far": int(row.chunks_so_far or 0),
        "chunk_count": int(row.chunk_count or 0),
        "pages": row.pages,
        "error_code": row.error_code,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_documents_for_tenant(tenant_id: str) -> list[dict]:
    from sqlalchemy import func

    sf = get_pg_session()
    items: list[dict] = []
    seen_sources: set[tuple[str, str]] = set()
    with sf.Session() as session:
        docs = (
            session.query(KnowledgeDocument)
            .filter(KnowledgeDocument.tenant_id == tenant_id)
            .order_by(KnowledgeDocument.created_at.desc())
            .all()
        )
        for row in docs:
            source = str(row.filename or "")
            items.append(
                {
                    "doc_id": row.id,
                    "source": source,
                    "name": source or "未命名文档",
                    "source_type": "pdf",
                    "chunk_count": int(row.chunk_count or 0),
                    "status": row.status,
                    "error_code": row.error_code,
                    "pages": row.pages,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
            seen_sources.add((source, "pdf"))
        rows = (
            session.query(
                KnowledgeChunk.source,
                KnowledgeChunk.source_type,
                func.count(KnowledgeChunk.id),
                func.max(KnowledgeChunk.created_at),
            )
            .filter(
                KnowledgeChunk.tenant_id == tenant_id,
                KnowledgeChunk.doc_id.is_(None),
            )
            .group_by(KnowledgeChunk.source, KnowledgeChunk.source_type)
            .order_by(func.max(KnowledgeChunk.created_at).desc())
            .all()
        )
        for source, source_type, chunk_count, created_at in rows:
            name = (source or "").strip() or "未命名文档"
            key = (source or "", source_type or "text")
            if key in seen_sources:
                continue
            items.append(
                {
                    "doc_id": None,
                    "source": source or "",
                    "name": name,
                    "source_type": source_type or "text",
                    "chunk_count": int(chunk_count or 0),
                    "status": "ready",
                    "error_code": None,
                    "pages": None,
                    "created_at": created_at.isoformat() if created_at else None,
                }
            )
    return items


def delete_document_for_tenant(tenant_id: str, source: str) -> int:
    sf = get_pg_session()
    with sf.Session() as session:
        doc_ids = [
            d.id
            for d in session.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.filename == source,
            )
            .all()
        ]
        deleted = (
            session.query(KnowledgeChunk)
            .filter(
                KnowledgeChunk.tenant_id == tenant_id,
                KnowledgeChunk.source == source,
            )
            .delete(synchronize_session=False)
        )
        if doc_ids:
            extra = (
                session.query(KnowledgeChunk)
                .filter(
                    KnowledgeChunk.tenant_id == tenant_id,
                    KnowledgeChunk.doc_id.in_(doc_ids),
                )
                .delete(synchronize_session=False)
            )
            deleted = int(deleted or 0) + int(extra or 0)
            session.query(KnowledgeDocument).filter(
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.id.in_(doc_ids),
            ).delete(synchronize_session=False)
        session.commit()
    return int(deleted or 0)


def retry_document(tenant_id: str, task_id: str) -> KnowledgeDocument:
    sf = get_pg_session()
    with sf.Session() as session:
        row = session.get(KnowledgeDocument, task_id)
        if row is None or str(row.tenant_id) != tenant_id:
            raise NexusAIException(ErrorCode.REQ_INVALID.value, "task_not_found")
        if str(row.status) != "failed":
            raise NexusAIException(ErrorCode.REQ_INVALID.value, "retry_only_failed")
        session.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == task_id).delete(
            synchronize_session=False
        )
        row.status = "queued"
        row.error_code = None
        row.chunks_so_far = 0
        row.chunk_count = 0
        row.pages = None
        row.updated_at = _now()
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def reclaim_stale(session: Session) -> int:
    cutoff = _now() - timedelta(minutes=STALE_MINUTES)
    result = session.execute(
        text(
            """
            UPDATE knowledge_documents
            SET status = 'queued', error_code = NULL, updated_at = :now
            WHERE status IN ('parsing', 'chunking', 'embedding')
              AND updated_at < :cutoff
            """
        ),
        {"cutoff": cutoff, "now": _now()},
    )
    return int(result.rowcount or 0)


def claim_next_queued() -> str | None:
    sf = get_pg_session()
    with sf.Session() as session:
        reclaim_stale(session)
        row = session.execute(
            text(
                """
                SELECT id FROM knowledge_documents
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            )
        ).fetchone()
        if row is None:
            session.commit()
            return None
        doc_id = str(row[0])
        session.execute(
            text(
                """
                UPDATE knowledge_documents
                SET status = 'parsing', updated_at = :now
                WHERE id = :id
                """
            ),
            {"id": doc_id, "now": _now()},
        )
        session.commit()
        return doc_id


def _update_doc(doc_id: str, **fields: object) -> None:
    sf = get_pg_session()
    with sf.Session() as session:
        row = session.get(KnowledgeDocument, doc_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = _now()
        session.commit()


def _fail(doc_id: str, error_code: str) -> None:
    _update_doc(doc_id, status="failed", error_code=error_code)


def _parse_and_chunk(doc: KnowledgeDocument):
    from packages.rag.core.knowledge_base import KnowledgeBaseManager
    from packages.rag.core.langchain_compat import Document

    kb = KnowledgeBaseManager()
    documents = kb.load_pdf_documents(doc.storage_path)
    non_empty = [d for d in documents if (d.page_content or "").strip()]
    if not non_empty:
        raise NexusAIException(
            ErrorCode.RAG_EMPTY_EXTRACT.value,
            "未提取到文本:扫描件或无文本层 PDF",
        )
    label = str(doc.filename or "document.pdf")
    for d in non_empty:
        meta = dict(d.metadata or {})
        meta["source"] = label
        meta["filename"] = label
        meta["source_type"] = "pdf"
        d.metadata = meta
    chunks: list[Document] = kb.split_documents(non_empty)
    return chunks


def process_document(
    doc_id: str, *, on_progress: Callable[[], None] | None = None
) -> bool:
    """Run parse→chunk→embed for one document. Safe for tests (no global claim)."""
    from packages.database.vector_ops import add_knowledge
    from packages.rag.cache import bump_epoch

    def _tick() -> None:
        if on_progress is None:
            return
        try:
            on_progress()
        except Exception:
            logger.debug("ingest progress tick skipped", exc_info=True)

    sf = get_pg_session()
    with sf.Session() as session:
        doc = session.get(KnowledgeDocument, doc_id)
        if doc is None:
            return False
        if str(doc.status) not in IN_FLIGHT:
            return False
        tenant_id = str(doc.tenant_id)
        org_unit_id = doc.org_unit_id
        session.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc_id).delete(
            synchronize_session=False
        )
        doc.status = "parsing"
        doc.error_code = None
        doc.chunks_so_far = 0
        doc.updated_at = _now()
        session.commit()
        session.refresh(doc)
        snapshot = KnowledgeDocument(
            id=doc.id,
            tenant_id=doc.tenant_id,
            org_unit_id=doc.org_unit_id,
            filename=doc.filename,
            storage_path=doc.storage_path,
            file_hash=doc.file_hash,
            status=doc.status,
        )

    try:
        _tick()
        chunks = _parse_and_chunk(snapshot)
        _tick()
        pages: set[int] = set()
        for ch in chunks:
            pn = page_no_from_meta(dict(ch.metadata or {}))
            if pn is not None:
                pages.add(pn)
        _update_doc(
            doc_id,
            status="chunking",
            chunk_count=len(chunks),
            pages=len(pages) or None,
            chunks_so_far=0,
        )
        _update_doc(doc_id, status="embedding")
        for i, ch in enumerate(chunks):
            meta = dict(ch.metadata or {})
            add_knowledge(
                text=ch.page_content,
                category=str(meta.get("category", "general")),
                tenant_id=tenant_id,
                metadata={
                    k: v
                    for k, v in meta.items()
                    if isinstance(v, (str, int, float, bool))
                },
                source=str(meta.get("source") or snapshot.filename or "")[:256],
                source_type="pdf",
                org_unit_id=org_unit_id,
                doc_id=doc_id,
                page_no=page_no_from_meta(meta),
            )
            _update_doc(doc_id, chunks_so_far=i + 1)
            _tick()
        _update_doc(
            doc_id,
            status="ready",
            chunk_count=len(chunks),
            chunks_so_far=len(chunks),
            error_code=None,
        )
        bump_epoch(tenant_id)
        return True
    except NexusAIException as exc:
        logger.warning("knowledge ingest failed doc=%s code=%s", doc_id, exc.code)
        _fail(doc_id, exc.code)
        return True
    except Exception:
        logger.exception("knowledge ingest crashed doc=%s", doc_id)
        _fail(doc_id, ErrorCode.INTERNAL_ERROR.value)
        return True


def process_one(*, on_progress: Callable[[], None] | None = None) -> bool:
    doc_id = claim_next_queued()
    if not doc_id:
        return False
    process_document(doc_id, on_progress=on_progress)
    return True
