"""Persist dig results into daily pool + run log (shared by HTTP + capability invoke)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from packages.content_ops.artifact_visibility import VISIBILITY_PRIVATE
from packages.content_ops.hotspot import (
    annotate_similar_to_previous,
    day_collection_hash,
    merge_hotspot_pool,
    normalize_title_token_set,
)
from packages.database.pgvector_session import ContentArtifact


def _title_excluded(title: str, excluded: list[str]) -> bool:
    key = normalize_title_token_set(title or "")
    if not key:
        return False
    for ex in excluded:
        if normalize_title_token_set(str(ex or "")) == key:
            return True
    return False


def filter_excluded_items(
    items: list[dict[str, Any]], excluded: list[str]
) -> list[dict[str, Any]]:
    if not excluded:
        return list(items)
    return [
        it
        for it in items
        if not _title_excluded(str(it.get("title") or ""), excluded)
    ]


def persist_dig_result(
    session: Session,
    *,
    tenant_id: str,
    result: dict[str, Any],
    save: bool = True,
    owner_user_id: str = "",
) -> dict[str, Any]:
    """Merge dig items into the owner's daily pool; run log is idempotent per owner."""
    owner = (owner_user_id or "").strip()
    if save and not owner:
        raise ValueError("owner_user_id_required")
    dig_hash = str(result.get("content_hash") or "")
    dig_items = list(result.get("items") or [])
    day = date.today().isoformat()
    day_hash = day_collection_hash(tenant_id, day)

    day_row = (
        session.query(ContentArtifact)
        .filter(
            ContentArtifact.tenant_id == tenant_id,
            ContentArtifact.owner_user_id == owner,
            ContentArtifact.kind == "hotspot_day",
            ContentArtifact.content_hash == day_hash,
        )
        .one_or_none()
    )
    existing_pool: list[dict[str, Any]] = []
    excluded: list[str] = []
    if day_row and isinstance(day_row.body, dict):
        existing_pool = list(day_row.body.get("items") or [])
        excluded = [str(x) for x in (day_row.body.get("excluded") or []) if x]

    dig_items = filter_excluded_items(dig_items, excluded)
    annotated = annotate_similar_to_previous(dig_items, existing_pool)
    out = dict(result)
    out["items"] = annotated
    out["count"] = len(annotated)
    out["day"] = day

    if not save:
        out.update(
            {
                "artifact_id": None,
                "day_artifact_id": None,
                "run_artifact_id": None,
                "new_count": 0,
                "skipped_duplicates": 0,
                "idempotent": False,
            }
        )
        return out

    day_artifact_id = day_row.id if day_row else None
    run_artifact_id = None
    new_count = 0
    skipped = 0
    idempotent = False

    existing_run = None
    if dig_hash:
        existing_run = (
            session.query(ContentArtifact)
            .filter(
                ContentArtifact.tenant_id == tenant_id,
                ContentArtifact.owner_user_id == owner,
                ContentArtifact.kind.in_(("hotspot_run", "hotspot")),
                ContentArtifact.content_hash == dig_hash,
            )
            .one_or_none()
        )

    if existing_run is not None:
        idempotent = True
        run_artifact_id = existing_run.id
        skipped = len(dig_items)
    else:
        merged, new_count, skipped = merge_hotspot_pool(existing_pool, dig_items)
        day_body = {
            "day": day,
            "items": merged,
            "count": len(merged),
            "excluded": excluded,
            "updated_from_dig_hash": dig_hash,
            "last_dig_evidence": result.get("dig_evidence"),
        }
        if day_row is None:
            day_artifact_id = str(uuid.uuid4())
            session.add(
                ContentArtifact(
                    id=day_artifact_id,
                    tenant_id=tenant_id,
                    kind="hotspot_day",
                    title=f"今日热点合集 {day}",
                    body=day_body,
                    content_hash=day_hash,
                    owner_user_id=owner,
                    visibility=VISIBILITY_PRIVATE,
                )
            )
        else:
            day_artifact_id = day_row.id
            day_row.title = f"今日热点合集 {day}"
            day_row.body = day_body

        run_artifact_id = str(uuid.uuid4())
        session.add(
            ContentArtifact(
                id=run_artifact_id,
                tenant_id=tenant_id,
                kind="hotspot_run",
                title=f"抓取 {len(dig_items)} 条 · 新增 {new_count}",
                body={
                    **out,
                    "new_count": new_count,
                    "skipped_duplicates": skipped,
                    "day_artifact_id": day_artifact_id,
                },
                content_hash=dig_hash or None,
                owner_user_id=owner,
                visibility=VISIBILITY_PRIVATE,
            )
        )

    out.update(
        {
            "artifact_id": day_artifact_id or run_artifact_id,
            "day_artifact_id": day_artifact_id,
            "run_artifact_id": run_artifact_id,
            "new_count": new_count,
            "skipped_duplicates": skipped,
            "idempotent": idempotent,
        }
    )
    return out
