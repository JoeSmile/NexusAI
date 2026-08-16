"""Extract plain text from style-upload files (not RAG ingest)."""

from __future__ import annotations

import io


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
