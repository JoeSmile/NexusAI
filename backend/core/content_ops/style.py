"""Content style (轨 B) + org profile helpers on tenant_config."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.database.pgvector_session import TenantConfig

DEFAULT_CREATOR_ID = "default"

DEFAULT_CONTENT_STYLE: dict[str, Any] = {
    "creator_id": DEFAULT_CREATOR_ID,
    "display_name": "默认主讲",
    "persona": "中性口语、亲和、专业",
    "addressing": ["同学们", "家长朋友们"],
    "catchphrases": [],
    "avg_sentence_len": "短句为主，约15字",
    "structure_habits": ["先抛痛点", "给方法", "结尾行动号召"],
    "taboos": ["不承诺提分", "不提竞品名", "不出现学员真名"],
    "sample_openers": ["先问你一个问题……"],
    "extracted_at": None,
    "source_doc_ids": [],
    "is_default": True,
}


def _ensure_row(session: Session, tenant_id: str) -> TenantConfig:
    row = (
        session.query(TenantConfig)
        .filter(TenantConfig.tenant_id == tenant_id)
        .one_or_none()
    )
    if row is None:
        row = TenantConfig(tenant_id=tenant_id, config={})
        session.add(row)
        session.flush()
    if not isinstance(row.config, dict):
        row.config = {}
    return row


def get_org_content_profile(session: Session, tenant_id: str) -> dict[str, Any]:
    row = (
        session.query(TenantConfig)
        .filter(TenantConfig.tenant_id == tenant_id)
        .one_or_none()
    )
    if row is None or not isinstance(row.config, dict):
        return {}
    raw = row.config.get("org_content_profile")
    return dict(raw) if isinstance(raw, dict) else {}


def set_org_content_profile(
    session: Session, tenant_id: str, profile: dict[str, Any]
) -> dict[str, Any]:
    row = _ensure_row(session, tenant_id)
    cfg = dict(row.config or {})
    cfg["org_content_profile"] = dict(profile)
    row.config = cfg
    session.add(row)
    return dict(profile)


def list_content_styles(session: Session, tenant_id: str) -> list[dict[str, Any]]:
    row = (
        session.query(TenantConfig)
        .filter(TenantConfig.tenant_id == tenant_id)
        .one_or_none()
    )
    if row is None or not isinstance(row.config, dict):
        return []
    styles = row.config.get("content_style")
    if not isinstance(styles, dict):
        return []
    out: list[dict[str, Any]] = []
    for cid, body in styles.items():
        if isinstance(body, dict):
            item = dict(body)
            item.setdefault("creator_id", str(cid))
            out.append(item)
    return out


def get_content_style(
    session: Session, tenant_id: str, creator_id: str = DEFAULT_CREATOR_ID
) -> dict[str, Any] | None:
    row = (
        session.query(TenantConfig)
        .filter(TenantConfig.tenant_id == tenant_id)
        .one_or_none()
    )
    if row is None or not isinstance(row.config, dict):
        return None
    styles = row.config.get("content_style")
    if not isinstance(styles, dict):
        return None
    body = styles.get(creator_id)
    if not isinstance(body, dict):
        return None
    item = dict(body)
    item.setdefault("creator_id", creator_id)
    return item


def upsert_content_style(
    session: Session,
    tenant_id: str,
    creator_id: str,
    style: dict[str, Any],
) -> dict[str, Any]:
    row = _ensure_row(session, tenant_id)
    cfg = dict(row.config or {})
    styles = dict(cfg.get("content_style") or {})
    if not isinstance(styles, dict):
        styles = {}
    merged = dict(style)
    merged["creator_id"] = creator_id
    merged["is_default"] = False
    if not merged.get("extracted_at"):
        merged["extracted_at"] = datetime.now(UTC).isoformat()
    styles[creator_id] = merged
    cfg["content_style"] = styles
    row.config = cfg
    session.add(row)
    return merged


def delete_content_style(
    session: Session, tenant_id: str, creator_id: str
) -> bool:
    row = (
        session.query(TenantConfig)
        .filter(TenantConfig.tenant_id == tenant_id)
        .one_or_none()
    )
    if row is None or not isinstance(row.config, dict):
        return False
    styles = row.config.get("content_style")
    if not isinstance(styles, dict) or creator_id not in styles:
        return False
    styles = dict(styles)
    del styles[creator_id]
    cfg = dict(row.config)
    cfg["content_style"] = styles
    row.config = cfg
    session.add(row)
    return True


def resolve_style_for_generate(
    session: Session,
    tenant_id: str,
    creator_id: str | None = None,
) -> dict[str, Any]:
    """Missing style → DEFAULT_CONTENT_STYLE (never raises)."""
    cid = (creator_id or DEFAULT_CREATOR_ID).strip() or DEFAULT_CREATOR_ID
    found = get_content_style(session, tenant_id, cid)
    if found:
        out = dict(found)
        out["is_default"] = False
        return out
    if cid != DEFAULT_CREATOR_ID:
        found_default = get_content_style(session, tenant_id, DEFAULT_CREATOR_ID)
        if found_default:
            out = dict(found_default)
            out["is_default"] = False
            return out
    return deepcopy(DEFAULT_CONTENT_STYLE)
