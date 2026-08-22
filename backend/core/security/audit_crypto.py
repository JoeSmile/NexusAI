"""AES-256-GCM for audit_logs sensitive text fields (Task 59 S4)."""

from __future__ import annotations

import base64
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_ENC_VERSION = 1
_REDACTED = "[ENCRYPTED]"


def audit_encryption_enabled() -> bool:
    return (os.getenv("AUDIT_ENCRYPTION_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def assert_audit_encryption_config() -> None:
    """Refuse boot when encryption is on but master key is missing/invalid."""
    if not audit_encryption_enabled():
        return
    _master_key_bytes()


class AuditTextCipher:
    """Per-row nonce envelope (same layout as KeyManager)."""

    def __init__(self, master_key_hex: str | None = None) -> None:
        key_bytes = (
            bytes.fromhex(master_key_hex)
            if master_key_hex
            else _master_key_bytes()
        )
        self._aesgcm = AESGCM(key_bytes)

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        nonce = os.urandom(12)
        ct = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, encrypted_b64: str) -> str:
        if not encrypted_b64:
            return ""
        raw = base64.b64decode(encrypted_b64)
        nonce, ct = raw[:12], raw[12:]
        return self._aesgcm.decrypt(nonce, ct, None).decode("utf-8")


def _master_key_bytes() -> bytes:
    key_hex = (os.getenv("AUDIT_ENCRYPTION_KEY") or "").strip()
    if not key_hex:
        raise RuntimeError(
            "AUDIT_ENCRYPTION_ENABLED=1 but AUDIT_ENCRYPTION_KEY is unset; "
            "generate: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    key_bytes = bytes.fromhex(key_hex)
    if len(key_bytes) != 32:
        raise ValueError("AUDIT_ENCRYPTION_KEY must be 32 bytes (64 hex chars)")
    return key_bytes


def _cipher_or_none() -> AuditTextCipher | None:
    if not audit_encryption_enabled():
        return None
    try:
        return AuditTextCipher()
    except Exception:
        logger.exception("audit encryption cipher unavailable")
        return None


def prepare_audit_text_fields(record: dict) -> dict:
    """Encrypt input/output text in-place when encryption is enabled."""
    cipher = _cipher_or_none()
    if cipher is None:
        record.setdefault("text_enc_version", 0)
        record.setdefault("input_text_enc", None)
        record.setdefault("output_text_enc", None)
        return record

    inp = str(record.get("input_text") or "")
    out = str(record.get("output_text") or "")
    record["input_text_enc"] = cipher.encrypt(inp) if inp else None
    record["output_text_enc"] = cipher.encrypt(out) if out else None
    record["input_text"] = _REDACTED if inp else ""
    record["output_text"] = _REDACTED if out else ""
    record["text_enc_version"] = _ENC_VERSION
    return record


def resolve_audit_text(
    row: object,
    *,
    can_decrypt: bool,
) -> tuple[str, str]:
    """Return (input_text, output_text) for API/export."""
    plain_in = str(getattr(row, "input_text", "") or "")
    plain_out = str(getattr(row, "output_text", "") or "")
    enc_in = getattr(row, "input_text_enc", None)
    enc_out = getattr(row, "output_text_enc", None)
    version = int(getattr(row, "text_enc_version", 0) or 0)

    if version < 1 or (not enc_in and not enc_out):
        return plain_in, plain_out

    if not can_decrypt:
        return (
            _REDACTED if enc_in or plain_in == _REDACTED else plain_in,
            _REDACTED if enc_out or plain_out == _REDACTED else plain_out,
        )

    cipher = _cipher_or_none()
    if cipher is None:
        return _REDACTED, _REDACTED

    try:
        return (
            cipher.decrypt(enc_in) if enc_in else plain_in,
            cipher.decrypt(enc_out) if enc_out else plain_out,
        )
    except Exception:
        logger.exception("audit text decrypt failed")
        return _REDACTED, _REDACTED


def backfill_encrypted_rows(batch_size: int = 200) -> int:
    """Encrypt legacy plaintext rows (idempotent). Returns rows updated."""
    cipher = _cipher_or_none()
    if cipher is None:
        return 0

    from sqlalchemy import text

    from backend.database.pgvector_session import get_pg_session

    updated = 0
    session_factory = get_pg_session()
    while True:
        with session_factory.Session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT id, input_text, output_text
                    FROM audit_logs
                    WHERE COALESCE(text_enc_version, 0) = 0
                      AND (
                        (input_text IS NOT NULL AND input_text != '' AND input_text != :redacted)
                        OR (output_text IS NOT NULL AND output_text != '' AND output_text != :redacted)
                      )
                    ORDER BY id
                    LIMIT :lim
                    """
                ),
                {"lim": batch_size, "redacted": _REDACTED},
            ).fetchall()
            if not rows:
                break
            for row in rows:
                inp = str(row.input_text or "")
                out = str(row.output_text or "")
                session.execute(
                    text(
                        """
                        UPDATE audit_logs
                        SET input_text_enc = :enc_in,
                            output_text_enc = :enc_out,
                            input_text = CASE WHEN :has_in THEN :redacted ELSE input_text END,
                            output_text = CASE WHEN :has_out THEN :redacted ELSE output_text END,
                            text_enc_version = :ver
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": row.id,
                        "enc_in": cipher.encrypt(inp) if inp else None,
                        "enc_out": cipher.encrypt(out) if out else None,
                        "has_in": bool(inp),
                        "has_out": bool(out),
                        "redacted": _REDACTED,
                        "ver": _ENC_VERSION,
                    },
                )
                updated += 1
            session.commit()
    return updated
