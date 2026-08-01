"""多模态 extractors — 依赖缺失 / 文件不存在（Task 23.01）"""

from __future__ import annotations

import builtins

import pytest

from backend.core.errors import ErrorCode
from backend.modules.rag.extractors.audio import (
    MultimodalDependencyError,
    extract_audio_text,
)
from backend.modules.rag.extractors.image import extract_image_text


@pytest.fixture
def block_optional_imports(monkeypatch):
    """阻止 whisper / paddleocr 真导入（CI 无 GPU / 大依赖）。"""
    real_import = builtins.__import__

    def _import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if root in {"faster_whisper", "whisper", "paddleocr", "paddle"}:
            raise ImportError(f"blocked:{name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import)


def test_audio_file_not_found():
    with pytest.raises(MultimodalDependencyError) as ei:
        extract_audio_text("/tmp/contextgate-missing-audio-xyz.wav")
    assert ei.value.code == ErrorCode.FILE_NOT_FOUND.value


def test_image_file_not_found():
    with pytest.raises(MultimodalDependencyError) as ei:
        extract_image_text("/tmp/contextgate-missing-image-xyz.png")
    assert ei.value.code == ErrorCode.FILE_NOT_FOUND.value


def test_audio_missing_deps(block_optional_imports, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF____WAVEfmt ")
    with pytest.raises(MultimodalDependencyError) as ei:
        extract_audio_text(wav)
    assert ei.value.code == ErrorCode.RAG_DEP_MISSING.value


def test_image_missing_deps(block_optional_imports, tmp_path):
    png = tmp_path / "i.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    with pytest.raises(MultimodalDependencyError) as ei:
        extract_image_text(png)
    assert ei.value.code == ErrorCode.RAG_DEP_MISSING.value
