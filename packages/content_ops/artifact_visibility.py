"""Task 45b.4 — artifact visibility: default private, explicit tenant share."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from packages.database.pgvector_session import ContentArtifact

VISIBILITY_PRIVATE = "private"
VISIBILITY_SHARED = "shared"
ALLOWED_VISIBILITY = frozenset({VISIBILITY_PRIVATE, VISIBILITY_SHARED})


class ArtifactShareForbidden(Exception):
    """Caller is not the owner of this artifact."""


class ArtifactNotFound(Exception):
    """No artifact in this tenant with that id."""


def visibility_filter(user_id: str) -> Any:
    uid = (user_id or "").strip()
    return or_(
        ContentArtifact.owner_user_id == uid,
        ContentArtifact.visibility == VISIBILITY_SHARED,
    )


def list_visible_artifacts(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
    kind: str | None = None,
    limit: int = 50,
) -> list[ContentArtifact]:
    q = session.query(ContentArtifact).filter(
        ContentArtifact.tenant_id == tenant_id,
        visibility_filter(user_id),
    )
    if kind:
        q = q.filter(ContentArtifact.kind == kind)
    return q.order_by(ContentArtifact.created_at.desc()).limit(limit).all()


def artifact_public_dict(row: ContentArtifact, *, viewer_id: str) -> dict[str, Any]:
    owner = str(row.owner_user_id or "")
    vis = str(row.visibility or VISIBILITY_PRIVATE)
    if vis not in ALLOWED_VISIBILITY:
        vis = VISIBILITY_PRIVATE
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "content_hash": row.content_hash,
        "creator_id": row.creator_id,
        "owner_user_id": owner,
        "visibility": vis,
        "is_owner": owner == (viewer_id or "").strip() and bool(owner),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def set_artifact_visibility(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
    artifact_id: str,
    visibility: str,
) -> ContentArtifact:
    vis = (visibility or "").strip().lower()
    if vis not in ALLOWED_VISIBILITY:
        raise ValueError("invalid_visibility")
    row = (
        session.query(ContentArtifact)
        .filter(
            ContentArtifact.tenant_id == tenant_id,
            ContentArtifact.id == artifact_id,
        )
        .one_or_none()
    )
    if row is None:
        raise ArtifactNotFound()
    if str(row.owner_user_id or "") != (user_id or "").strip():
        raise ArtifactShareForbidden()
    row.visibility = vis
    return row
