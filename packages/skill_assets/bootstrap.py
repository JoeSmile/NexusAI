"""Bootstrap builtin skill_assets (Task 66 slice 2)."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from backend.database.pgvector_session import SkillAsset, get_pg_session
from packages.skill_assets.builtin_catalog import BUILTIN_SKILL_ASSET_CATALOG
from packages.skill_assets.gates import GateReject, run_publish_gates
from packages.skill_assets.service import create_draft, publish

logger = logging.getLogger(__name__)


def _find_published_by_name(session: Session, tenant_id: str, name: str) -> SkillAsset | None:
    return (
        session.query(SkillAsset)
        .filter(
            SkillAsset.tenant_id == tenant_id,
            SkillAsset.name == name,
            SkillAsset.status == "published",
        )
        .one_or_none()
    )


def validate_builtin_catalog() -> list[str]:
    """Run publish gates on all catalog entries (no DB). Returns skill_ids."""
    ok: list[str] = []
    for entry in BUILTIN_SKILL_ASSET_CATALOG:
        run_publish_gates(
            cot_template=entry["cot_template"],
            ir_skeleton=entry["ir_skeleton"],
            required_permissions=entry["required_permissions"],
        )
        ok.append(entry["skill_id"])
    return ok


def bootstrap_builtin_skill_assets(
    *,
    tenant_id: str,
    owner_user_id: str,
    publish_now: bool = True,
) -> dict[str, str]:
    """Create draft + publish builtin skill_assets; skip if name already published.

    Returns mapping skill_id → asset_id (published or existing).
    """
    validate_builtin_catalog()
    sf = get_pg_session()
    out: dict[str, str] = {}
    with sf.Session() as session:
        for entry in BUILTIN_SKILL_ASSET_CATALOG:
            name = entry["name"]
            existing = _find_published_by_name(session, tenant_id, name)
            if existing is not None:
                out[entry["skill_id"]] = str(existing.id)
                continue
            row = create_draft(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                name=name,
                description=entry["description"],
                cot_template=entry["cot_template"],
                ir_skeleton=entry["ir_skeleton"],
                visibility=entry.get("visibility", "tenant_public"),
                embed=True,
            )
            asset_id = str(row.id)
            if publish_now:
                try:
                    published = publish(
                        tenant_id=tenant_id,
                        asset_id=asset_id,
                        actor_user_id=owner_user_id,
                        required_permissions=entry["required_permissions"],
                    )
                    asset_id = str(published.id)
                except GateReject as exc:
                    logger.warning("builtin skill_asset publish blocked %s: %s", name, exc)
                    raise
            out[entry["skill_id"]] = asset_id
    logger.info("bootstrap builtin skill_assets tenant=%s count=%s", tenant_id, len(out))
    return out
