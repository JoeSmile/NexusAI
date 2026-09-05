"""Offerings catalog service + default seeds."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from packages.database.pgvector_session import Offering

DEFAULT_OFFERINGS: list[dict[str, Any]] = [
    {
        "id": "wf.hotspot_dig",
        "tenant_id": "*",
        "dept": "content_growth",
        "name": "抓取相关热点",
        "description": "按机构定位挖掘教育向热点/选题（手动激活）",
        "status": "implemented",
        "target_kind": "capability",
        "target_id": "hotspot.dig",
        "sort_order": 10,
        "meta": {"icon": "trending"},
    },
    {
        "id": "wf.script_gen",
        "tenant_id": "*",
        "dept": "content_growth",
        "name": "生成口播稿",
        "description": "按主讲风格与热点生成口播（无风格时用默认）",
        "status": "implemented",
        "target_kind": "capability",
        "target_id": "script.gen",
        "sort_order": 20,
        "meta": {"icon": "mic"},
    },
    {
        "id": "wf.storyboard",
        "tenant_id": "*",
        "dept": "content_growth",
        "name": "分镜稿",
        "description": "分镜表格式预览（后续 Wave）",
        "status": "placeholder",
        "target_kind": "capability",
        "target_id": "",
        "sort_order": 30,
        "meta": {},
    },
]


def ensure_default_offerings(session: Session) -> int:
    """Insert missing global seeds. Returns number created."""
    created = 0
    now = datetime.utcnow()
    for row in DEFAULT_OFFERINGS:
        existing = session.query(Offering).filter(Offering.id == row["id"]).one_or_none()
        if existing:
            continue
        session.add(
            Offering(
                id=row["id"],
                tenant_id=row["tenant_id"],
                dept=row["dept"],
                name=row["name"],
                description=row["description"],
                status=row["status"],
                target_kind=row["target_kind"],
                target_id=row["target_id"],
                sort_order=row["sort_order"],
                meta=dict(row.get("meta") or {}),
                created_at=now,
                updated_at=now,
            )
        )
        created += 1
    if created:
        session.flush()
    return created


def list_offerings(
    session: Session,
    *,
    tenant_id: str,
    dept: str | None = None,
) -> list[dict[str, Any]]:
    ensure_default_offerings(session)
    try:
        from packages.content_ops.workflow_seed import (
            ensure_builtin_hotspot_workflow,
            ensure_builtin_llm_generate_workflow,
        )

        ensure_builtin_hotspot_workflow(session, tenant_id=tenant_id)
        ensure_builtin_llm_generate_workflow(session, tenant_id=tenant_id)
    except Exception:
        pass
    q = session.query(Offering).filter(
        (Offering.tenant_id == "*") | (Offering.tenant_id == tenant_id)
    )
    if dept:
        q = q.filter(Offering.dept == dept)
    rows = q.order_by(Offering.sort_order.asc(), Offering.id.asc()).all()
    return [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "dept": r.dept,
            "name": r.name,
            "description": r.description,
            "status": r.status,
            "target_kind": r.target_kind,
            "target_id": r.target_id,
            "sort_order": r.sort_order,
            "meta": r.meta or {},
        }
        for r in rows
    ]


def get_offering(session: Session, offering_id: str) -> dict[str, Any] | None:
    ensure_default_offerings(session)
    r = session.query(Offering).filter(Offering.id == offering_id).one_or_none()
    if r is None:
        return None
    return {
        "id": r.id,
        "tenant_id": r.tenant_id,
        "dept": r.dept,
        "name": r.name,
        "description": r.description,
        "status": r.status,
        "target_kind": r.target_kind,
        "target_id": r.target_id,
        "sort_order": r.sort_order,
        "meta": r.meta or {},
    }
