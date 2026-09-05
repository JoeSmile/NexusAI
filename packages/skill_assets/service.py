"""CRUD / lifecycle / vector search for skill_assets (Task 43.2)."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from packages.audit import write_audit_sync
from packages.database.embeddings import embed_text
from packages.database.pgvector_session import SkillAsset, get_pg_session
from packages.skill_assets.gates import GateReject, run_publish_gates

logger = logging.getLogger(__name__)

STATUSES = frozenset({"draft", "published", "deprecated"})
VISIBILITIES = frozenset({"private", "tenant_public"})


def _hit_threshold() -> float:
    raw = (os.getenv("SKILL_ASSET_HIT_THRESHOLD") or "").strip()
    if not raw:
        return 0.75
    try:
        return float(raw)
    except ValueError:
        return 0.75


def create_draft(
    *,
    tenant_id: str,
    owner_user_id: str,
    name: str,
    description: str = "",
    cot_template: str = "",
    ir_skeleton: dict[str, Any] | None = None,
    visibility: str = "private",
    embed: bool = True,
) -> SkillAsset:
    if visibility not in VISIBILITIES:
        visibility = "private"
    sf = get_pg_session()
    with sf.Session() as session:
        row = SkillAsset(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            name=name.strip()[:128],
            description=(description or "")[:2000],
            cot_template=cot_template or "",
            ir_skeleton=dict(ir_skeleton or {}),
            version=1,
            status="draft",
            visibility=visibility,
            usage_stats={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        if embed:
            try:
                row.embedding = embed_text(
                    f"{row.name}\n{row.description}\n{row.cot_template[:500]}",
                    tenant_id=tenant_id,
                )
            except Exception:
                logger.debug("skill_asset embed failed", exc_info=True)
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def publish(
    *,
    tenant_id: str,
    asset_id: str,
    actor_user_id: str,
    required_permissions: list[str] | None = None,
) -> SkillAsset:
    """CAS draft→published + gates。冲突 → 409。"""
    sf = get_pg_session()
    with sf.Session() as session:
        row = (
            session.query(SkillAsset)
            .filter(
                SkillAsset.id == asset_id,
                SkillAsset.tenant_id == tenant_id,
            )
            .one_or_none()
        )
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "SKA_404", "message": "not_found"},
            )
        if row.status != "draft":
            raise HTTPException(
                status_code=409,
                detail={"code": "SKA_409", "message": "not_draft"},
            )
        try:
            perms = run_publish_gates(
                cot_template=row.cot_template,
                ir_skeleton=row.ir_skeleton
                if isinstance(row.ir_skeleton, dict)
                else {},
                required_permissions=required_permissions,
            )
        except GateReject as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

        res = session.execute(
            text(
                "UPDATE skill_assets SET status='published', updated_at=:now, "
                "version=version+1 WHERE id=:id AND status='draft'"
            ),
            {"id": asset_id, "now": datetime.utcnow()},
        )
        if res.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail={"code": "SKA_409", "message": "publish_cas_conflict"},
            )
        session.refresh(row)
        from packages.skill_assets.workflow_sync import sync_skill_workflow_on_publish

        workflow_id = sync_skill_workflow_on_publish(
            session, asset=row, created_by=actor_user_id
        )
        stats = dict(row.usage_stats or {})
        stats["required_permissions"] = perms
        if workflow_id:
            stats["workflow_id"] = workflow_id
        row.usage_stats = stats
        session.commit()
        write_audit_sync(
            {
                "tenant_id": tenant_id,
                "user_id": actor_user_id,
                "action": "skill_assets.publish",
                "trace_id": asset_id,
                "input_text": "",
                "output_text": f"name={row.name}:v={row.version}",
                "model": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "latency_ms": 0.0,
                "error_code": None,
                "ip_address": "",
                "user_agent": "",
                "credential_kind": None,
                "key_id": None,
                "run_id": None,
                "node_id": None,
                "created_at": datetime.utcnow(),
            }
        )
        session.refresh(row)
        session.expunge(row)
        return row


def deprecate(*, tenant_id: str, asset_id: str) -> SkillAsset:
    sf = get_pg_session()
    with sf.Session() as session:
        row = (
            session.query(SkillAsset)
            .filter(
                SkillAsset.id == asset_id,
                SkillAsset.tenant_id == tenant_id,
            )
            .one_or_none()
        )
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "SKA_404", "message": "not_found"},
            )
        if row.status == "deprecated":
            return row
        if row.status != "published":
            raise HTTPException(
                status_code=409,
                detail={"code": "SKA_409", "message": "not_published"},
            )
        from packages.skill_assets.workflow_sync import archive_skill_workflow

        archive_skill_workflow(
            session, tenant_id=tenant_id, asset_id=asset_id
        )
        row.status = "deprecated"
        stats = dict(row.usage_stats or {})
        stats.pop("workflow_id", None)
        row.usage_stats = stats
        row.updated_at = datetime.utcnow()
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def reject_draft(*, tenant_id: str, asset_id: str) -> bool:
    """管理员拒绝候选：删除 draft。"""
    sf = get_pg_session()
    with sf.Session() as session:
        row = (
            session.query(SkillAsset)
            .filter(
                SkillAsset.id == asset_id,
                SkillAsset.tenant_id == tenant_id,
                SkillAsset.status == "draft",
            )
            .one_or_none()
        )
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def search_published(
    *,
    tenant_id: str,
    query: str,
    limit: int = 5,
    min_score: float | None = None,
    user_id: str | None = None,
) -> list[tuple[SkillAsset, float]]:
    """向量相似度检索 published。

    - ``user_id`` 提供 → 可见性过滤:``tenant_public`` 全租户 + ``private`` 仅 owner
      （评审 08-14 F2 拍板:private 字段已入表,不区分 = 字段空转）。
    - ``user_id=None`` → 全租户 published 视图（系统/管理侧:miner 去重,防 publish
      撞部分唯一索引 (tenant_id, name) WHERE status='published'）。
    """
    threshold = _hit_threshold() if min_score is None else float(min_score)
    vec = embed_text(query or "", tenant_id=tenant_id)
    vec_str = "[" + ",".join(str(v) for v in vec) + "]"
    sf = get_pg_session()
    with sf.Session() as session:
        vis_cond = (
            "AND (visibility = 'tenant_public' OR owner_user_id = :uid)"
            if user_id
            else ""
        )
        sql = text(
            f"""
            SELECT id,
                   1 - (embedding <=> CAST(:vec AS vector)) AS similarity
            FROM skill_assets
            WHERE tenant_id = :tid
              AND status = 'published'
              AND embedding IS NOT NULL
              {vis_cond}
              AND 1 - (embedding <=> CAST(:vec AS vector)) >= :min_score
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :lim
            """
        )
        params: dict[str, Any] = {
            "vec": vec_str,
            "tid": tenant_id,
            "min_score": threshold,
            "lim": limit,
        }
        if user_id:
            params["uid"] = user_id
        rows = session.execute(sql, params).fetchall()
        out: list[tuple[SkillAsset, float]] = []
        for r in rows:
            asset = session.query(SkillAsset).filter(SkillAsset.id == r.id).one()
            session.expunge(asset)
            out.append((asset, float(r.similarity)))
        return out


def bump_usage_by_id(
    *,
    tenant_id: str,
    asset_id: str,
    tokens: int = 0,
    ok: bool = True,
) -> None:
    """Fail-soft usage bump（task_plan 命中后调用）。"""
    try:
        sf = get_pg_session()
        with sf.Session() as session:
            asset = (
                session.query(SkillAsset)
                .filter(
                    SkillAsset.id == asset_id,
                    SkillAsset.tenant_id == tenant_id,
                )
                .one_or_none()
            )
            if asset is None:
                return
            bump_usage(session, asset, tokens=tokens, ok=ok)
            session.commit()
    except Exception:
        logger.debug("bump_usage_by_id failed", exc_info=True)


def bump_usage(session: Session, asset: SkillAsset, *, tokens: int = 0, ok: bool = True) -> None:
    stats = dict(asset.usage_stats or {})
    stats["uses"] = int(stats.get("uses") or 0) + 1
    if ok:
        stats["successes"] = int(stats.get("successes") or 0) + 1
    prev = float(stats.get("avg_tokens") or 0.0)
    n = int(stats.get("uses") or 1)
    stats["avg_tokens"] = ((prev * (n - 1)) + tokens) / n
    asset.usage_stats = stats
    asset.updated_at = datetime.utcnow()


def list_skill_assets(
    *,
    tenant_id: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 200,
) -> list[SkillAsset]:
    """Admin list — optional tenant scope and status filter."""
    sf = get_pg_session()
    with sf.Session() as session:
        query = session.query(SkillAsset)
        if tenant_id:
            query = query.filter(SkillAsset.tenant_id == tenant_id)
        if status:
            query = query.filter(SkillAsset.status == status.strip().lower())
        rows = query.order_by(SkillAsset.updated_at.desc()).limit(max(1, limit)).all()
        if q:
            needle = q.strip().lower()
            rows = [
                r
                for r in rows
                if needle in (r.name or "").lower()
                or needle in (r.description or "").lower()
            ]
        for row in rows:
            session.expunge(row)
        return rows


def get_skill_asset(*, tenant_id: str, asset_id: str) -> SkillAsset | None:
    sf = get_pg_session()
    with sf.Session() as session:
        row = (
            session.query(SkillAsset)
            .filter(SkillAsset.id == asset_id, SkillAsset.tenant_id == tenant_id)
            .one_or_none()
        )
        if row is not None:
            session.expunge(row)
        return row


def evolution_stats(*, tenant_id: str | None = None) -> dict[str, Any]:
    """Aggregate skill_assets metrics for admin evolution panel."""
    sf = get_pg_session()
    with sf.Session() as session:
        query = session.query(SkillAsset)
        if tenant_id:
            query = query.filter(SkillAsset.tenant_id == tenant_id)
        rows = query.all()
    by_status: dict[str, int] = {"draft": 0, "published": 0, "deprecated": 0}
    mined_queue = 0
    total_uses = 0
    total_successes = 0
    for row in rows:
        st = str(row.status or "draft")
        by_status[st] = by_status.get(st, 0) + 1
        if st == "draft" and "mined_from" in str(row.description or ""):
            mined_queue += 1
        stats = dict(row.usage_stats or {})
        total_uses += int(stats.get("uses") or 0)
        total_successes += int(stats.get("successes") or 0)
    hit_rate = (total_successes / total_uses) if total_uses else 0.0
    return {
        "total": len(rows),
        "by_status": by_status,
        "mined_draft_queue": mined_queue,
        "total_uses": total_uses,
        "cache_hit_rate_proxy": round(hit_rate, 4),
    }
