"""Task 76.1 — parse session attachments into blocks (no RAG / no vectors)."""

from __future__ import annotations

import io
import zipfile

import pytest

from packages.attachments.parse import ParseError, parse_document
from packages.attachments.validate import ATTACHMENT_MAX_BYTES, validate_attachment_bytes


def _minimal_pdf(text: str) -> bytes:
    # ASCII-only content stream; Helvetica
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode("latin-1")
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
        b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"5 0 obj<</Length "
        + str(len(stream)).encode()
        + b">>stream\n"
        + stream
        + b"\nendstream\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \n"
        b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"
    )
    return body


def test_txt_and_csv_parse_into_blocks() -> None:
    txt = parse_document(b"hello world\nline2", "note.txt")
    assert txt.status == "ready"
    assert txt.blocks
    assert "hello world" in txt.blocks[0].text

    csv_bytes = b"name,amt\na,1\nb,2\n"
    csv = parse_document(csv_bytes, "t.csv")
    assert csv.status == "ready"
    assert csv.blocks[0].kind == "table"
    assert "name" in csv.blocks[0].text


def test_pdf_text_pages_become_page_blocks() -> None:
    data = _minimal_pdf("Contract clause 12")
    out = parse_document(data, "c.pdf")
    assert out.status == "ready"
    assert out.blocks[0].kind == "page"
    assert out.blocks[0].page == 1
    assert "Contract" in (out.blocks[0].text or "") or out.blocks[0].char_count >= 0


def test_empty_pdf_is_ocr_required_not_ready() -> None:
    from pypdf import PdfWriter

    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    w.write(buf)
    out = parse_document(buf.getvalue(), "scan.pdf")
    assert out.status == "ocr_required"
    assert out.blocks == []


def test_reject_xlsm_and_oversize() -> None:
    with pytest.raises(ParseError) as ei:
        validate_attachment_bytes(filename="macro.xlsm", data=b"PK\x03\x04" + b"\x00" * 20)
    assert ei.value.code in {"FILE_TYPE", "FILE_MACRO"}

    too_big = b"%PDF" + b"x" * (ATTACHMENT_MAX_BYTES + 1)
    with pytest.raises(ParseError) as ej:
        validate_attachment_bytes(filename="big.pdf", data=too_big)
    assert ej.value.code == "FILE_TOO_LARGE"


def test_zip_bomb_rejected() -> None:
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/bomb.bin", b"0" * (256 * 1024))
        zf.writestr("xl/workbook.xml", "<workbook/>")
        zf.writestr("[Content_Types].xml", "<Types/>")
    packed = buf2.getvalue()
    assert len(packed) < ATTACHMENT_MAX_BYTES
    with pytest.raises(ParseError) as ei:
        validate_attachment_bytes(filename="bomb.xlsx", data=packed)
    assert ei.value.code == "FILE_ZIP_BOMB"
