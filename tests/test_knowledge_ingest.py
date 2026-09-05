"""Task 83 — async RAG ingest: documents table, enqueue, worker, hash dedupe."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from packages.database.pgvector_session import (
    KnowledgeChunk,
    KnowledgeDocument,
    get_pg_session,
)
from packages.errors import ErrorCode, NexusAIException


@pytest.fixture()
def ingest_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
    from packages.database.embeddings import EMBED_DIM

    monkeypatch.setattr(
        "packages.database.vector_ops.embedding_uses_hash_fallback",
        lambda tenant_id=None: False,
    )
    monkeypatch.setattr(
        "packages.database.vector_ops.embed_result_is_semantic",
        lambda: True,
    )
    monkeypatch.setattr(
        "packages.database.vector_ops.embed_text",
        lambda *a, **k: [0.01] * EMBED_DIM,
    )
    sf = get_pg_session()
    yield sf
    with sf.Session() as session:
        session.query(KnowledgeChunk).filter(
            KnowledgeChunk.tenant_id.like("ing-%")
        ).delete(synchronize_session=False)
        session.query(KnowledgeDocument).filter(
            KnowledgeDocument.tenant_id.like("ing-%")
        ).delete(synchronize_session=False)
        session.commit()


def _pdf_bytes() -> bytes:
    return b"%PDF-1.4 fake-not-parsed"


def test_knowledge_document_model_fields() -> None:
    assert KnowledgeDocument.__tablename__ == "knowledge_documents"
    assert hasattr(KnowledgeDocument, "file_hash")
    assert hasattr(KnowledgeDocument, "status")
    assert hasattr(KnowledgeChunk, "doc_id")
    assert hasattr(KnowledgeChunk, "page_no")


def test_enqueue_writes_queued_row_and_file(ingest_db, tmp_path: Path) -> None:
    from packages.rag.ingest import enqueue_pdf_bytes

    tid = f"ing-{uuid.uuid4().hex[:8]}"
    body = _pdf_bytes()
    ack = enqueue_pdf_bytes(
        tenant_id=tid,
        org_unit_id=None,
        filename="手册.pdf",
        data=body,
    )
    assert ack.duplicate is False
    assert ack.status == "queued"
    assert ack.doc_id
    stored = Path(ack.storage_path)
    assert stored.is_file()
    assert stored.read_bytes() == body
    assert "knowledge" in stored.parts
    assert hashlib.sha256(body).hexdigest() == ack.file_hash


def test_enqueue_duplicate_hash_returns_existing(ingest_db) -> None:
    from packages.rag.ingest import enqueue_pdf_bytes

    tid = f"ing-{uuid.uuid4().hex[:8]}"
    body = _pdf_bytes() + b"-dup"
    first = enqueue_pdf_bytes(
        tenant_id=tid, org_unit_id=None, filename="a.pdf", data=body
    )
    second = enqueue_pdf_bytes(
        tenant_id=tid, org_unit_id=None, filename="b.pdf", data=body
    )
    assert second.duplicate is True
    assert second.doc_id == first.doc_id


def test_process_one_marks_failed_on_embed_unavailable(
    ingest_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.rag import ingest

    tid = f"ing-{uuid.uuid4().hex[:8]}"
    ack = ingest.enqueue_pdf_bytes(
        tenant_id=tid, org_unit_id=None, filename="x.pdf", data=_pdf_bytes()
    )
    monkeypatch.setattr(
        ingest,
        "_parse_and_chunk",
        lambda *_a, **_k: (_ for _ in ()).throw(
            NexusAIException(
                ErrorCode.EMBED_UNAVAILABLE.value, "embedding_api_unavailable"
            )
        ),
    )
    did = ingest.process_document(ack.doc_id)
    assert did is True
    with ingest_db.Session() as session:
        row = session.get(KnowledgeDocument, ack.doc_id)
        assert row is not None
        assert row.status == "failed"
        assert row.error_code == ErrorCode.EMBED_UNAVAILABLE.value


def test_process_one_writes_chunks_with_doc_id(
    ingest_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.rag import ingest
    from packages.rag.core.langchain_compat import Document

    tid = f"ing-{uuid.uuid4().hex[:8]}"
    ack = ingest.enqueue_pdf_bytes(
        tenant_id=tid, org_unit_id=None, filename="p.pdf", data=_pdf_bytes()
    )

    def _parse(doc: KnowledgeDocument):
        return [
            Document(page_content="hello page", metadata={"page": 0, "source": "p.pdf"}),
        ]

    monkeypatch.setattr(ingest, "_parse_and_chunk", _parse)
    ticks = {"n": 0}
    assert ingest.process_document(ack.doc_id, on_progress=lambda: ticks.update(n=ticks["n"] + 1)) is True
    assert ticks["n"] >= 2
    with ingest_db.Session() as session:
        row = session.get(KnowledgeDocument, ack.doc_id)
        assert row is not None
        assert row.status == "ready"
        chunks = (
            session.query(KnowledgeChunk)
            .filter(KnowledgeChunk.doc_id == ack.doc_id)
            .all()
        )
        assert len(chunks) == 1
        assert chunks[0].page_no == 1
        assert chunks[0].content == "hello page"
