"""Content style (轨 B) + org profile helpers on tenant_config."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from packages.database.pgvector_session import TenantConfig

DEFAULT_CREATOR_ID = "default"

DEFAULT_CONTENT_STYLE: dict[str, Any] = {
    "creator_id": DEFAULT_CREATOR_ID,
    "display_name": "默认主讲",
    "persona": "中性口语、亲和、专业,像懂行的朋友聊天,不端不装",
    "addressing": ["家长朋友们", "同学们"],
    "catchphrases": [],
    "avg_sentence_len": "短句为主,8-15字,有停顿感",
    "structure_habits": ["黄金3秒钩子", "场景化痛点", "2-3个方法点", "软性行动号召"],
    "taboos": ["不承诺提分", "不提竞品名", "不出现学员真名", "不贩卖焦虑"],
    "sample_openers": [
        "先问你一个问题:……(痛点开场)",
        "是不是……?很多家长/同学都栽在这(共鸣开场)",
        "有个方法,90%的人不知道……(反常识开场)",
    ],
    # ── 说话逻辑层（2026-09-05 深度化：可迁移的"讲法"，不只词表）──
    "explain_style": "怎么讲道理：先抛结论再给理由；用生活类比把抽象概念讲白",
    "example_style": "怎么讲例子：爱用具体学生的场景+前后对比，不用编造的数字",
    "transition_style": "怎么转场：用设问衔接('那怎么办？')，不用'第二点'式干转",
    "pacing": "节奏：中速偏快，关键句前停顿；爱用排比收束方法段",
    "emotional_tone": "情绪基调：温和但有力度；焦虑点到为止，不吓唬",
    "rhetoric": "修辞偏好：多用设问/反问、'是不是''有没有'；偶尔自嘲拉近距离",
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
