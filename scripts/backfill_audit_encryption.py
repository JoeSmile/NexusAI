"""Backfill legacy audit_logs plaintext into encrypted columns (Task 59 S4)."""

from __future__ import annotations

import os
import sys

from packages.security.audit_crypto import (
    audit_encryption_enabled,
    backfill_encrypted_rows,
)


def main() -> int:
    if not audit_encryption_enabled():
        print("AUDIT_ENCRYPTION_ENABLED is off — nothing to do", file=sys.stderr)
        return 1
    if not (os.getenv("AUDIT_ENCRYPTION_KEY") or "").strip():
        print("AUDIT_ENCRYPTION_KEY is required", file=sys.stderr)
        return 1
    n = backfill_encrypted_rows()
    print(f"backfilled_rows={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
