"""Style file text extraction tests."""

from __future__ import annotations

import pytest

from backend.core.content_ops.file_text import (
    StyleUploadRejected,
    allowed_style_suffix,
    extract_text_from_bytes,
    validate_style_upload,
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


def test_validate_rejects_exe_magic() -> None:
    with pytest.raises(StyleUploadRejected) as ei:
        validate_style_upload(
            filename="speech.exe",
            content_type="application/octet-stream",
            data=b"MZ" + b"\x00" * 64,
        )
    assert ei.value.status_code == 415


def test_validate_rejects_html() -> None:
    with pytest.raises(StyleUploadRejected) as ei:
        validate_style_upload(
            filename="x.html",
            content_type="text/html",
            data=b"<!DOCTYPE html><html>",
        )
    assert ei.value.status_code == 415


def test_validate_rejects_oversize() -> None:
    with pytest.raises(StyleUploadRejected) as ei:
        validate_style_upload(
            filename="big.txt",
            content_type="text/plain",
            data=b"a" * (5 * 1024 * 1024 + 1),
        )
    assert ei.value.status_code == 413


def test_validate_stores_uuid_not_original_name() -> None:
    stored = validate_style_upload(
        filename="../../../etc/passwd.txt",
        content_type="text/plain",
        data="同学们好，今天就一件事，把课讲清楚。".encode(),
    )
    assert stored.endswith(".txt")
    assert "passwd" not in stored
    assert "/" not in stored
    assert ".." not in stored
    assert len(stored.split(".")[0]) == 32
