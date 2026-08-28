"""Terms of service — version lookup + acceptance gate (Task 55 slice 3)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from sqlalchemy import text

from packages.errors import ErrorCode, NexusAIException
from backend.database.pgvector_session import get_pg_session

_TERMS_NOT_ACCEPTED = ErrorCode.TERMS_NOT_ACCEPTED.value

_VALID_KINDS = frozenset({"company_key", "byok", "privacy", "general"})


def is_terms_enforcement_enabled() -> bool:
    return os.getenv("TERMS_ENFORCEMENT_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def resolve_mode_kind(credential_kind: str = "company") -> str:
    if credential_kind == "byok":
        return "byok"
    return "company_key"


def required_terms_kinds(credential_kind: str = "company") -> list[str]:
    mode = resolve_mode_kind(credential_kind)
    return ["general", "privacy", mode]


def get_current_terms(kind: str) -> dict | None:
    if kind not in _VALID_KINDS:
        return None
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        row = session.execute(
            text(
                """
                SELECT id, version, kind, effective_at, content_md
                FROM terms_versions
                WHERE kind = :kind AND effective_at <= now()
                ORDER BY effective_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"kind": kind},
        ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row.id),
        "version": row.version,
        "kind": row.kind,
        "effective_at": row.effective_at.isoformat() if row.effective_at else None,
        "content_md": row.content_md,
    }


def list_pending_terms(
    *,
    tenant_id: str,
    user_id: str,
    credential_kind: str = "company",
) -> list[dict]:
    pending: list[dict] = []
    for kind in required_terms_kinds(credential_kind):
        current = get_current_terms(kind)
        if current is None:
            continue
        if has_accepted(
            tenant_id=tenant_id,
            user_id=user_id,
            kind=kind,
            version=current["version"],
        ):
            continue
        pending.append(current)
    return pending


def has_accepted(
    *,
    tenant_id: str,
    user_id: str,
    kind: str,
    version: str,
) -> bool:
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        row = session.execute(
            text(
                """
                SELECT 1 FROM terms_acceptances
                WHERE tenant_id = :tid AND user_id = :uid
                  AND kind = :kind AND version = :ver
                LIMIT 1
                """
            ),
            {"tid": tenant_id, "uid": user_id, "kind": kind, "ver": version},
        ).fetchone()
    return row is not None


def record_acceptance(
    *,
    tenant_id: str,
    user_id: str,
    kind: str,
    version: str,
    ip_address: str | None = None,
) -> dict:
    current = get_current_terms(kind)
    if current is None:
        raise NexusAIException(_TERMS_NOT_ACCEPTED, "terms_kind_not_found")
    if current["version"] != version:
        raise NexusAIException(_TERMS_NOT_ACCEPTED, "terms_version_mismatch")

    now = datetime.now(UTC).replace(tzinfo=None)
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        session.execute(
            text(
                """
                INSERT INTO terms_acceptances (
                    tenant_id, user_id, kind, version, accepted_at, ip_address
                ) VALUES (
                    :tid, :uid, :kind, :ver, :at, :ip
                )
                ON CONFLICT (tenant_id, user_id, kind, version) DO NOTHING
                """
            ),
            {
                "tid": tenant_id,
                "uid": user_id,
                "kind": kind,
                "ver": version,
                "at": now,
                "ip": ip_address,
            },
        )
        session.commit()
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "kind": kind,
        "version": version,
        "accepted_at": now.isoformat(),
    }


def enforce_terms_for_chat(
    *,
    tenant_id: str,
    user_id: str,
    credential_kind: str = "company",
    ip_address: str | None = None,
) -> None:
    """Raise NexusAIException when required terms are not accepted."""
    if not is_terms_enforcement_enabled():
        return
    pending = list_pending_terms(
        tenant_id=tenant_id,
        user_id=user_id,
        credential_kind=credential_kind,
    )
    if not pending:
        return
    kinds = [p["kind"] for p in pending]
    raise NexusAIException(
        _TERMS_NOT_ACCEPTED,
        "terms_not_accepted",
        detail=",".join(kinds),
    )
