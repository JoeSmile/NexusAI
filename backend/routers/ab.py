"""A/B 实验管理 API — /api/ab/*"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.core.ab.service import assign_variant, get_active_experiment, record_event
from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_permission
from backend.database.pgvector_session import get_pg_session

router = APIRouter(prefix="/ab", tags=["ab"])


class CreateExperimentRequest(BaseModel):
    experiment_id: str
    name: str
    description: str = ""
    groups: list[str] = Field(default_factory=lambda: ["A", "B"])
    weights: list[float] = Field(default_factory=lambda: [0.5, 0.5])
    variant_configs: dict[str, dict] = Field(default_factory=dict)
    enabled: bool = True


class EventRequest(BaseModel):
    experiment_id: str
    group: str
    event_type: str = "conversion"
    event_data: dict = Field(default_factory=dict)
    session_id: str | None = None


@router.post("/experiments")
async def create_experiment(
    req: CreateExperimentRequest,
    tenant: TenantContext = Depends(require_permission("admin:*")),
):
    """创建或更新 A/B 实验（variant_configs 写入 extra_metadata）。"""
    if len(req.groups) != len(req.weights):
        raise HTTPException(
            status_code=400,
            detail={"code": "AB_001", "message": "groups_weights_mismatch"},
        )
    meta = {"variant_configs": req.variant_configs, "tenant_id": tenant.tenant_id}
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        existing = session.execute(
            text(
                "SELECT id FROM ab_test_experiments WHERE experiment_id = :eid"
            ),
            {"eid": req.experiment_id},
        ).fetchone()
        if existing:
            session.execute(
                text(
                    """
                    UPDATE ab_test_experiments
                    SET name = :name, description = :desc, groups = :groups,
                        weights = :weights, extra_metadata = :meta,
                        enabled = :en, updated_at = :now
                    WHERE experiment_id = :eid
                    """
                ),
                {
                    "name": req.name,
                    "desc": req.description,
                    "groups": json.dumps(req.groups),
                    "weights": json.dumps(req.weights),
                    "meta": json.dumps(meta, ensure_ascii=False),
                    "en": req.enabled,
                    "now": datetime.utcnow(),
                    "eid": req.experiment_id,
                },
            )
        else:
            session.execute(
                text(
                    """
                    INSERT INTO ab_test_experiments
                        (experiment_id, name, description, groups, weights,
                         start_date, enabled, extra_metadata, created_at, updated_at)
                    VALUES
                        (:eid, :name, :desc, :groups, :weights,
                         :now, :en, :meta, :now, :now)
                    """
                ),
                {
                    "eid": req.experiment_id,
                    "name": req.name,
                    "desc": req.description,
                    "groups": json.dumps(req.groups),
                    "weights": json.dumps(req.weights),
                    "en": req.enabled,
                    "meta": json.dumps(meta, ensure_ascii=False),
                    "now": datetime.utcnow(),
                },
            )
        session.commit()
    return {"status": "ok", "experiment_id": req.experiment_id}


@router.get("/experiments")
async def list_experiments(
    tenant: TenantContext = Depends(require_permission("admin:*")),
):
    """列出实验。"""
    _ = tenant
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        rows = session.execute(
            text(
                """
                SELECT experiment_id, name, description, groups, weights,
                       enabled, extra_metadata, created_at, updated_at
                FROM ab_test_experiments
                ORDER BY created_at DESC
                """
            )
        ).fetchall()
    out = []
    for r in rows:
        try:
            meta = json.loads(r.extra_metadata or "{}")
        except Exception:
            meta = {}
        out.append(
            {
                "experiment_id": r.experiment_id,
                "name": r.name,
                "description": r.description or "",
                "groups": json.loads(r.groups or "[]"),
                "weights": json.loads(r.weights or "[]"),
                "enabled": bool(r.enabled),
                "variant_configs": meta.get("variant_configs") or {},
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
        )
    return out


@router.get("/experiments/{experiment_id}")
async def get_experiment(
    experiment_id: str,
    tenant: TenantContext = Depends(require_permission("admin:*")),
):
    _ = tenant
    exp = get_active_experiment(experiment_id)
    if exp is None:
        # 也允许查未启用的
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            row = session.execute(
                text(
                    """
                    SELECT experiment_id, name, description, groups, weights,
                           enabled, extra_metadata
                    FROM ab_test_experiments WHERE experiment_id = :eid
                    """
                ),
                {"eid": experiment_id},
            ).fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail={"code": "AB_002", "message": "experiment_not_found"},
            )
        meta = json.loads(row.extra_metadata or "{}")
        return {
            "experiment_id": row.experiment_id,
            "name": row.name,
            "description": row.description or "",
            "groups": json.loads(row.groups or "[]"),
            "weights": json.loads(row.weights or "[]"),
            "enabled": bool(row.enabled),
            "variant_configs": meta.get("variant_configs") or {},
        }
    return exp


@router.post("/assign")
async def assign(
    experiment_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """为当前用户分配变体（调试用）。"""
    result = assign_variant(tenant.user_id, experiment_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "AB_002", "message": "no_active_experiment"},
        )
    return result


@router.post("/events")
async def post_event(
    req: EventRequest,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    record_event(
        user_id=tenant.user_id,
        experiment_id=req.experiment_id,
        group=req.group,
        event_type=req.event_type,
        event_data=req.event_data,
        session_id=req.session_id,
    )
    return {"status": "ok"}


@router.get("/stats/{experiment_id}")
async def experiment_stats(
    experiment_id: str,
    tenant: TenantContext = Depends(require_permission("admin:*")),
):
    """按变体聚合曝光/事件数。"""
    _ = tenant
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        rows = session.execute(
            text(
                """
                SELECT "group", event_type, COUNT(*) AS cnt
                FROM ab_test_events
                WHERE experiment_id = :eid
                GROUP BY "group", event_type
                ORDER BY "group", event_type
                """
            ),
            {"eid": experiment_id},
        ).fetchall()
        assigns = session.execute(
            text(
                """
                SELECT "group", COUNT(*) AS cnt
                FROM ab_test_group_assignments
                WHERE experiment_id = :eid
                GROUP BY "group"
                """
            ),
            {"eid": experiment_id},
        ).fetchall()
    return {
        "experiment_id": experiment_id,
        "assignments": {r.group: r.cnt for r in assigns},
        "events": [
            {"group": r.group, "event_type": r.event_type, "count": r.cnt} for r in rows
        ],
    }
