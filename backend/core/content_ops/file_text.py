"""Extract plain text from style-upload files (not RAG ingest)."""

from __future__ import annotations

import io
import uuid
import zipfile

STYLE_MAX_BYTES = 5 * 1024 * 1024
_ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "text/plain",
        "text/markdown",
        "text/x-markdown",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
        "",
    }
)


class StyleUploadRejected(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def _sniff_kind(data: bytes) -> str | None:
    if not data:
        return None
    if data.startswith(b"MZ") or data.startswith(b"\x7fELF"):
        return None
    if data.startswith(b"%PDF"):
        return "pdf"
    head = data[:512].lstrip().lower()
    if head.startswith((b"<html", b"<!doctype html", b"<?php", b"<script")):
        return None
    if data.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
            if any(n.startswith("word/") for n in names):
                return "docx"
        except zipfile.BadZipFile:
            return None
        return None
    return "txt"


def validate_style_upload(
    *, filename: str, content_type: str | None, data: bytes
) -> str:
    """Return UUID storage name (with sniffed suffix). Raises StyleUploadRejected."""
    if len(data) > STYLE_MAX_BYTES:
        raise StyleUploadRejected(413, "STYLE_FILE_TOO_LARGE", "file_exceeds_5mb")
    if not data:
        raise StyleUploadRejected(400, "STYLE_FILE_EMPTY", "empty_file")
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype not in _ALLOWED_CONTENT_TYPES:
        raise StyleUploadRejected(415, "STYLE_FILE_TYPE", "unsupported_content_type")
    kind = _sniff_kind(data)
    if kind is None:
        raise StyleUploadRejected(415, "STYLE_FILE_TYPE", "unsupported_magic")
    suffix = (filename or "").rsplit(".", 1)[-1].lower() if filename else ""
    if kind == "txt" and suffix not in ("txt", "md", ""):
        raise StyleUploadRejected(415, "STYLE_FILE_TYPE", "suffix_magic_mismatch")
    if kind == "pdf" and suffix not in ("pdf", ""):
        raise StyleUploadRejected(415, "STYLE_FILE_TYPE", "suffix_magic_mismatch")
    if kind == "docx" and suffix not in ("docx", ""):
        raise StyleUploadRejected(415, "STYLE_FILE_TYPE", "suffix_magic_mismatch")
    return f"{uuid.uuid4().hex}.{kind}"


def extract_text_from_bytes(*, filename: str, data: bytes) -> str:
    """Parse txt/pdf/docx for style extract only. Raises ValueError on bad type."""
    name = (filename or "upload.bin").lower()
    if name.endswith(".txt") or name.endswith(".md"):
        for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader  # type: ignore[no-redef]

        reader = PdfReader(io.BytesIO(data))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
        if not text:
            raise ValueError("pdf_empty_text")
        return text

    if name.endswith(".docx"):
        # Prefer python-docx if installed; else zip+xml fallback for plain paragraphs
        try:
            import docx  # type: ignore[import-untyped]

            doc = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs if p.text).strip()
        except ImportError:
            import xml.etree.ElementTree as ET
            import zipfile

            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                xml = zf.read("word/document.xml")
            root = ET.fromstring(xml)
            texts = [
                t.text
                for t in root.iter(
                    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
                )
                if t.text
            ]
            # also without ns fallback
            if not texts:
                texts = [t.text for t in root.iter() if t.tag.endswith("}t") and t.text]
            return "\n".join(texts).strip()

    if name.endswith(".doc"):
        raise ValueError("doc_legacy_unsupported_use_docx_or_txt")

    raise ValueError("unsupported_style_file_type")


def allowed_style_suffix(filename: str) -> bool:
    n = (filename or "").lower()
    return n.endswith((".txt", ".md", ".pdf", ".docx"))
