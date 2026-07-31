"""文件上传安全加固 — MIME 校验 + UUID 重命名"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

ALLOWED_MIME = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/gif": b"GIF89a",
    "application/pdf": b"%PDF",
    "text/plain": None,
}

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".pdf", ".txt"}
MAX_FILE_SIZE = 10 * 1024 * 1024


def detect_mime(content: bytes) -> str | None:
    """通过文件头检测真实 MIME 类型"""
    for mime_type, magic in ALLOWED_MIME.items():
        if magic and content.startswith(magic):
            return mime_type
    return None


def validate_file(filename: str, content: bytes, content_type: str) -> tuple[bool, str]:
    """验证文件 — (通过, 错误信息)"""
    if len(content) > MAX_FILE_SIZE:
        return False, "FILE_001: 文件超过 10MB 限制"

    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"FILE_002: 不允许的文件类型 {ext}"

    if ext != ".txt":
        real_mime = detect_mime(content)
        if real_mime is None:
            return False, "FILE_002: 无法识别文件类型"

    return True, ""


def sanitize_filename(original: str) -> tuple[str, str]:
    """生成安全的存储文件名 — (存储名, 扩展名)"""
    base = os.path.basename(original.replace("\\", "/"))
    ext = os.path.splitext(base)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ""
    safe_name = f"{uuid.uuid4().hex}{ext}"
    return safe_name, ext


UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
try:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
