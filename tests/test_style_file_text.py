"""Style file text extraction tests."""

from __future__ import annotations

import pytest

from backend.core.content_ops.file_text import (
    allowed_style_suffix,
    extract_text_from_bytes,
)


def test_allowed_suffix():
    assert allowed_style_suffix("a.PDF")
    assert allowed_style_suffix("b.docx")
    assert allowed_style_suffix("c.txt")
    assert not allowed_style_suffix("d.doc")
    assert not allowed_style_suffix("e.xlsx")


def test_extract_txt():
    text = extract_text_from_bytes(
        filename="speech.txt", data="同学们好，咱们今天就一件事。".encode()
    )
    assert "同学们" in text


def test_extract_legacy_doc_rejected():
    with pytest.raises(ValueError, match="doc_legacy"):
        extract_text_from_bytes(filename="old.doc", data=b"x")
