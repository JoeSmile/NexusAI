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
    "audio/mpeg": b"ID3",
    "audio/wav": b"RIFF",
}

# 扩展名 → 逻辑类型
EXT_KIND = {
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".gif": "image",
    ".pdf": "pdf",
    ".txt": "text",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
}

ALLOWED_EXTENSIONS = set(EXT_KIND)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 多模态音频可更大


def detect_mime(content: bytes) -> str | None:
    """通过文件头检测真实 MIME 类型"""
    for mime_type, magic in ALLOWED_MIME.items():
        if magic and content.startswith(magic):
            return mime_type
    # mp3 无 ID3 时常见帧同步
    if len(content) >= 2 and content[0] == 0xFF and (content[1] & 0xE0) == 0xE0:
        return "audio/mpeg"
    return None


def file_kind(filename: str) -> str | None:
    ext = os.path.splitext(filename)[1].lower()
    return EXT_KIND.get(ext)


def validate_file(filename: str, content: bytes, content_type: str) -> tuple[bool, str]:
    """验证文件 — (通过, 错误信息)"""
    if len(content) > MAX_FILE_SIZE:
        return False, "FILE_001: 文件超过大小限制"

    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"FILE_002: 不允许的文件类型 {ext}"

    kind = EXT_KIND.get(ext)
    if kind in ("text", "audio") and ext in (".txt", ".m4a", ".mp3", ".wav"):
        # m4a 容器魔数多样，扩展名放行；mp3/wav 尽量校验
        if ext == ".wav" and not content.startswith(b"RIFF"):
            return False, "FILE_002: 无效的 WAV 文件"
        if ext == ".txt":
            return True, ""
        if ext == ".mp3":
            real = detect_mime(content)
            if real not in (None, "audio/mpeg"):
                return False, "FILE_002: 无法识别音频类型"
        return True, ""

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
