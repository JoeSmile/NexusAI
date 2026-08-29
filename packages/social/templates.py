"""Template precipitation — hard hash merge (Task 52 S5).

Skeleton (句式/段落结构/引导类型) 归一化 → SHA256 前 16 位 = template_key.
同 tenant + platform + template_key 合并 sample_count。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from packages.database.pgvector_session import SocialResult, SocialTemplate

_SLOT_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,}")


def _slot_kind(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return "empty"
    if any(k in t for k in ("钩", "hook", "痛点", "提问", "反常识", "数字")):
        return "hook"
    if any(k in t for k in ("方法", "步骤", "清单", "第一", "第二", "干货")):
        return "method"
    if any(k in t for k in ("号召", "关注", "评论", "cta", "行动")):
        return "cta"
    if any(k in t for k in ("痛", "焦虑", "场景")):
        return "pain"
    # strip fill words → length bucket only
    chars = len(_SLOT_RE.findall(t))
    if chars <= 2:
        return "short"
    if chars <= 8:
        return "mid"
    return "long"


def skeleton_from_structure(structure: dict[str, Any] | None) -> dict[str, Any]:
    """Drop fill; keep structural skeleton for hashing."""
    s = structure or {}
    outline = s.get("outline") or []
    hooks = s.get("hooks") or []
    topics = s.get("topics") or []
    replicables = s.get("replicables") or []
    return {
        "template_type": str(s.get("template_type") or "generic"),
        "hook_slots": [_slot_kind(str(h)) for h in hooks[:6]],
        "outline_slots": [
            _slot_kind(str(x.get("role") or x.get("text") or x) if isinstance(x, dict) else str(x))
            for x in outline[:12]
        ],
        "topic_n": min(len(topics), 8),
        "replicable_n": min(len(replicables), 8),
    }


def template_key_from_structure(structure: dict[str, Any] | None) -> str:
    sk = skeleton_from_structure(structure)
    raw = json.dumps(sk, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def upsert_template(
    session: Session,
    *,
    tenant_id: str,
    platform: str,
    structure: dict[str, Any],
) -> SocialTemplate:
    """Merge by template_key; store skeleton-oriented structure_json."""
    key = template_key_from_structure(structure)
    ttype = str(structure.get("template_type") or "generic")
    row = (
        session.query(SocialTemplate)
        .filter(
            SocialTemplate.tenant_id == tenant_id,
            SocialTemplate.platform == platform,
            SocialTemplate.template_key == key,
        )
        .one_or_none()
    )
    skeleton = {
        "skeleton": skeleton_from_structure(structure),
        "sample_structure": {
            "hooks": structure.get("hooks") or [],
            "outline": structure.get("outline") or [],
            "topics": structure.get("topics") or [],
            "replicables": structure.get("replicables") or [],
            "template_type": ttype,
        },
    }
    if row is None:
        row = SocialTemplate(
            tenant_id=tenant_id,
            platform=platform,
            template_key=key,
            template_type=ttype,
            structure_json=skeleton,
            sample_count=1,
            usage_count=0,
        )
        session.add(row)
    else:
        row.sample_count = int(row.sample_count or 0) + 1
        row.template_type = row.template_type or ttype
        # keep first skeleton; refresh sample_structure lightly
        prev = dict(row.structure_json or {})
        prev["sample_structure"] = skeleton["sample_structure"]
        prev["skeleton"] = prev.get("skeleton") or skeleton["skeleton"]
        row.structure_json = prev
    session.flush()
    return row


def link_result_template(
    session: Session,
    *,
    result: SocialResult,
    tenant_id: str,
    platform: str,
) -> SocialTemplate | None:
    if not result.structure_json:
        return None
    tpl = upsert_template(
        session,
        tenant_id=tenant_id,
        platform=platform,
        structure=dict(result.structure_json),
    )
    result.template_id = tpl.id
    session.flush()
    return tpl


def pick_template_for_replica(
    session: Session,
    *,
    tenant_id: str,
    platform: str,
    result: SocialResult,
) -> SocialTemplate | None:
    """Prefer result.template_id; else precipitate from structure; else hottest template."""
    if result.template_id:
        tpl = (
            session.query(SocialTemplate)
            .filter(
                SocialTemplate.id == result.template_id,
                SocialTemplate.tenant_id == tenant_id,
            )
            .one_or_none()
        )
        if tpl:
            return tpl
    if result.structure_json:
        return link_result_template(
            session,
            result=result,
            tenant_id=tenant_id,
            platform=platform,
        )
    return (
        session.query(SocialTemplate)
        .filter(
            SocialTemplate.tenant_id == tenant_id,
            SocialTemplate.platform == platform,
        )
        .order_by(SocialTemplate.usage_count.desc(), SocialTemplate.sample_count.desc())
        .first()
    )
