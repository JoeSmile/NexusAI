"""Idempotent persist for script.gen artifacts (HTTP + capability share)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy.orm import Session

from packages.content_ops.artifact_visibility import VISIBILITY_PRIVATE
from packages.database.pgvector_session import ContentArtifact


def script_content_hash(tenant_id: str, owner_user_id: str, script: str) -> str:
    raw = f"{tenant_id}|{owner_user_id}|{script}".encode()
    return hashlib.sha256(raw).hexdigest()


def persist_script_artifact(
    session: Session,
    *,
    tenant_id: str,
    owner_user_id: str,
    creator_id: str,
    title: str,
    body: dict[str, Any],
) -> str:
    owner = (owner_user_id or "").strip()
    if not owner:
        raise ValueError("owner_user_id_required")
    script = str((body or {}).get("script") or "")
    digest = script_content_hash(tenant_id, owner, script)
    existing = (
        session.query(ContentArtifact)
        .filter(
            ContentArtifact.tenant_id == tenant_id,
            ContentArtifact.owner_user_id == owner,
            ContentArtifact.kind == "script",
            ContentArtifact.content_hash == digest,
        )
        .one_or_none()
    )
    if existing is not None:
        return str(existing.id)
    artifact_id = str(uuid.uuid4())
    session.add(
        ContentArtifact(
            id=artifact_id,
            tenant_id=tenant_id,
            kind="script",
            title=str(title or "口播稿")[:200],
            body=dict(body or {}),
            content_hash=digest,
            creator_id=creator_id or "default",
            owner_user_id=owner,
            visibility=VISIBILITY_PRIVATE,
        )
    )
    session.flush()
    return artifact_id
