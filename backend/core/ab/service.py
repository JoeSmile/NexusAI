"""A/B 分流服务 — 确定性 hash + 持久化 assignment。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import text

from backend.database.pgvector_session import get_pg_session


def _parse_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _stable_bucket(user_id: str, experiment_id: str) -> float:
    """返回 [0, 1) 的确定性分数。"""
    digest = hashlib.sha256(f"{experiment_id}:{user_id}".encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def get_active_experiment(experiment_id: str | None = None) -> dict[str, Any] | None:
    """取启用中的实验；未指定 id 时取最新一条 enabled。"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        if experiment_id:
            row = session.execute(
                text(
                    """
                    SELECT experiment_id, name, description, groups, weights,
                           extra_metadata, enabled, start_date, end_date
                    FROM ab_test_experiments
                    WHERE experiment_id = :eid AND enabled = true
                    """
                ),
                {"eid": experiment_id},
            ).fetchone()
        else:
            row = session.execute(
                text(
                    """
                    SELECT experiment_id, name, description, groups, weights,
                           extra_metadata, enabled, start_date, end_date
                    FROM ab_test_experiments
                    WHERE enabled = true
                      AND (start_date IS NULL OR start_date <= now())
                      AND (end_date IS NULL OR end_date >= now())
                    ORDER BY updated_at DESC NULLS LAST, created_at DESC
                    LIMIT 1
                    """
                )
            ).fetchone()
    if not row:
        return None

    groups = _parse_json(row.groups, ["A", "B"])
    weights = _parse_json(row.weights, [0.5, 0.5])
    meta = _parse_json(row.extra_metadata, {})
    if not isinstance(groups, list) or not groups:
        groups = ["A", "B"]
    if not isinstance(weights, list) or len(weights) != len(groups):
        weights = [1.0 / len(groups)] * len(groups)
    total = float(sum(float(w) for w in weights)) or 1.0
    weights = [float(w) / total for w in weights]

    return {
        "experiment_id": row.experiment_id,
        "name": row.name,
        "description": row.description or "",
        "groups": groups,
        "weights": weights,
        "variant_configs": meta.get("variant_configs") or {},
        "extra_metadata": meta,
        "enabled": bool(row.enabled),
    }


def assign_variant(
    user_id: str,
    experiment_id: str | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any] | None:
    """确定性分流；已有 assignment 则复用。"""
    exp = get_active_experiment(experiment_id)
    if exp is None:
        return None

    eid = exp["experiment_id"]
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        existing = session.execute(
            text(
                """
                SELECT group FROM ab_test_group_assignments
                WHERE user_id = :uid AND experiment_id = :eid
                LIMIT 1
                """
            ),
            {"uid": user_id, "eid": eid},
        ).fetchone()
        if existing:
            variant = existing.group
        else:
            score = _stable_bucket(user_id, eid)
            cumulative = 0.0
            variant = exp["groups"][-1]
            for group, weight in zip(exp["groups"], exp["weights"], strict=False):
                cumulative += weight
                if score < cumulative:
                    variant = group
                    break
            if persist:
                session.execute(
                    text(
                        """
                        INSERT INTO ab_test_group_assignments
                            (user_id, experiment_id, "group", assigned_at, updated_at)
                        VALUES (:uid, :eid, :grp, :now, :now)
                        """
                    ),
                    {
                        "uid": user_id,
                        "eid": eid,
                        "grp": variant,
                        "now": datetime.utcnow(),
                    },
                )
                session.commit()

    config = (exp.get("variant_configs") or {}).get(variant) or {}
    return {
        "experiment_id": eid,
        "variant": variant,
        "variant_config": config if isinstance(config, dict) else {},
        "name": exp.get("name"),
    }


def record_event(
    *,
    user_id: str,
    experiment_id: str,
    group: str,
    event_type: str,
    event_data: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> None:
    """记录曝光 / 转化事件。"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        session.execute(
            text(
                """
                INSERT INTO ab_test_events
                    (user_id, experiment_id, "group", event_type, event_data,
                     session_id, timestamp, created_at)
                VALUES
                    (:uid, :eid, :grp, :etype, :edata, :sid, :now, :now)
                """
            ),
            {
                "uid": user_id,
                "eid": experiment_id,
                "grp": group,
                "etype": event_type,
                "edata": json.dumps(event_data or {}, ensure_ascii=False),
                "sid": session_id,
                "now": datetime.utcnow(),
            },
        )
        session.commit()
