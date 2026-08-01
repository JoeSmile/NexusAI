"""file_sanitizer 多模态扩展校验（Task 23.01）"""

from __future__ import annotations

from backend.core.file_sanitizer import file_kind, sanitize_filename, validate_file


def test_file_kind_audio_image():
    assert file_kind("a.mp3") == "audio"
    assert file_kind("b.wav") == "audio"
    assert file_kind("c.m4a") == "audio"
    assert file_kind("d.png") == "image"
    assert file_kind("e.jpg") == "image"
    assert file_kind("f.exe") is None


def test_validate_png_ok():
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    ok, err = validate_file("x.png", content, "image/png")
    assert ok
    assert err == ""


def test_validate_wav_ok():
    content = b"RIFF" + b"\x00" * 12
    ok, err = validate_file("x.wav", content, "audio/wav")
    assert ok


def test_validate_wav_bad_magic():
    ok, err = validate_file("x.wav", b"NOTWAV", "audio/wav")
    assert not ok
    assert err.startswith("FILE_002")


def test_validate_rejected_extension():
    ok, err = validate_file("x.exe", b"MZ", "application/octet-stream")
    assert not ok
    assert "FILE_002" in err


def test_validate_too_large(monkeypatch):
    import backend.core.file_sanitizer as fs

    monkeypatch.setattr(fs, "MAX_FILE_SIZE", 8)
    ok, err = fs.validate_file("huge.txt", b"0123456789", "text/plain")
    assert not ok
    assert err.startswith("FILE_001")


def test_sanitize_filename_keeps_ext():
    name, ext = sanitize_filename("../../evil.PNG")
    assert ext == ".png"
    assert name.endswith(".png")
    assert ".." not in name
