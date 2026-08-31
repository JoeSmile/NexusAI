"""Magic sniff + size / macro / zip-bomb gates for chat attachments."""

from __future__ import annotations

import io
import zipfile

from packages.attachments.errors import ParseError

ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024
ZIP_MAX_UNCOMPRESSED = 80 * 1024 * 1024
ZIP_MAX_FILES = 256
ZIP_MAX_RATIO = 200

_KIND_BY_SUFFIX = {
    "pdf": "pdf",
    "txt": "txt",
    "md": "txt",
    "csv": "csv",
    "docx": "docx",
    "xlsx": "xlsx",
}


def _suffix(filename: str) -> str:
    name = (filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def _sniff_kind(data: bytes, filename: str) -> str:
    suf = _suffix(filename)
    if suf == "xlsm":
        raise ParseError("FILE_MACRO", "xlsm_not_allowed")
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
        except zipfile.BadZipFile as exc:
            raise ParseError("FILE_TYPE", "bad_zip") from exc
        lower = [n.lower() for n in names]
        if any("vbaproject.bin" in n or n.endswith(".xlsm") for n in lower):
            raise ParseError("FILE_MACRO", "macro_not_allowed")
        if any(n.startswith("word/") for n in lower):
            return "docx"
        if any(n.startswith("xl/") for n in lower):
            return "xlsx"
        raise ParseError("FILE_TYPE", "unsupported_zip")
    if suf == "csv":
        return "csv"
    if suf in ("txt", "md", ""):
        return "txt"
    if suf == "pdf":
        raise ParseError("FILE_TYPE", "suffix_magic_mismatch")
    raise ParseError("FILE_TYPE", "unsupported_magic")


def _check_zip_bomb(data: bytes) -> None:
    if not data.startswith(b"PK"):
        return
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise ParseError("FILE_TYPE", "bad_zip") from exc
    if len(infos) > ZIP_MAX_FILES:
        raise ParseError("FILE_ZIP_BOMB", "too_many_zip_entries")
    total = 0
    for info in infos:
        if info.file_size < 0:
            raise ParseError("FILE_ZIP_BOMB", "negative_size")
        total += int(info.file_size)
        if info.compress_size and info.file_size // max(info.compress_size, 1) > ZIP_MAX_RATIO:
            raise ParseError("FILE_ZIP_BOMB", "zip_ratio")
        if total > ZIP_MAX_UNCOMPRESSED:
            raise ParseError("FILE_ZIP_BOMB", "uncompressed_too_large")


def validate_attachment_bytes(*, filename: str, data: bytes) -> str:
    """Return sniffed kind. Raises ParseError."""
    if not data:
        raise ParseError("FILE_EMPTY", "empty_file")
    if len(data) > ATTACHMENT_MAX_BYTES:
        raise ParseError("FILE_TOO_LARGE", "file_exceeds_20mb")
    suf = _suffix(filename)
    if suf == "xlsm":
        raise ParseError("FILE_MACRO", "xlsm_not_allowed")
    _check_zip_bomb(data)
    kind = _sniff_kind(data, filename)
    expected = _KIND_BY_SUFFIX.get(suf)
    if expected and expected != kind and not (expected == "txt" and kind == "txt"):
        raise ParseError("FILE_TYPE", "suffix_magic_mismatch")
    return kind
