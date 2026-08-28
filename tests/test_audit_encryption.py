"""Task 59 slice 1 — audit text encryption (S4)."""

from __future__ import annotations

import pytest

from packages.security.audit_crypto import (
    AuditTextCipher,
    prepare_audit_text_fields,
    resolve_audit_text,
)


@pytest.fixture
def cipher(monkeypatch: pytest.MonkeyPatch) -> AuditTextCipher:
    key = "a" * 64
    monkeypatch.setenv("AUDIT_ENCRYPTION_ENABLED", "1")
    monkeypatch.setenv("AUDIT_ENCRYPTION_KEY", key)
    return AuditTextCipher(master_key_hex=key)


def test_encrypt_roundtrip(cipher: AuditTextCipher) -> None:
    enc = cipher.encrypt("hello audit")
    assert enc
    assert cipher.decrypt(enc) == "hello audit"


def test_prepare_audit_text_fields_encrypts(monkeypatch: pytest.MonkeyPatch) -> None:
    key = "b" * 64
    monkeypatch.setenv("AUDIT_ENCRYPTION_ENABLED", "1")
    monkeypatch.setenv("AUDIT_ENCRYPTION_KEY", key)
    rec = prepare_audit_text_fields({"input_text": "secret in", "output_text": "secret out"})
    assert rec["text_enc_version"] == 1
    assert rec["input_text"] == "[ENCRYPTED]"
    assert rec["input_text_enc"]
    assert rec["output_text_enc"]


class _Row:
    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_resolve_audit_text_auditor_decrypts(
    monkeypatch: pytest.MonkeyPatch, cipher: AuditTextCipher
) -> None:
    enc_in = cipher.encrypt("plain in")
    row = _Row(
        input_text="[ENCRYPTED]",
        output_text="",
        input_text_enc=enc_in,
        output_text_enc=None,
        text_enc_version=1,
    )
    inp, out = resolve_audit_text(row, can_decrypt=True)
    assert inp == "plain in"
    assert out == ""


def test_resolve_audit_text_non_auditor_redacted(
    monkeypatch: pytest.MonkeyPatch, cipher: AuditTextCipher
) -> None:
    enc_in = cipher.encrypt("plain in")
    row = _Row(
        input_text="[ENCRYPTED]",
        output_text="",
        input_text_enc=enc_in,
        output_text_enc=None,
        text_enc_version=1,
    )
    inp, _ = resolve_audit_text(row, can_decrypt=False)
    assert inp == "[ENCRYPTED]"
