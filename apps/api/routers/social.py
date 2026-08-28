"""Task 52 S3 — /api/social endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.core.audit import log_audit
from packages.social import service as social_svc
from packages.social.exceptions import (
    PlatformNotOpenError,
    SocialCostAlertError,
    TikHubBalanceError,
    TikHubConfigError,
    TikHubRateLimitError,
    TikHubUpstreamError,
)
from packages.social.export_xlsx import build_analysis_xlsx
from backend.database.pgvector_session import (
    PGVectorSession,
    SocialContent,
    SocialResult,
    SocialTask,
    SocialTemplate,
)
from packages.auth.models import TenantContext
from packages.auth.permissions import require_permission

router = APIRouter(
    prefix="/api/social",
    tags=["social"],
    dependencies=[Depends(require_permission("chat:write"))],
)


def _db_session():
    return PGVectorSession().Session()


class ProbeBody(BaseModel):
    platform: str
    account_key: str


class TaskBody(BaseModel):
    platform: str
    account_key: str
    phase: Literal["fetch", "analyze", "full"] = "full"
    fetch_limit: int = Field(default=20, ge=1, le=50)


class BrandBody(BaseModel):
    name: str | None = None
    business: str | None = None
    style: str | None = None
    audience: str | None = None


class ReplicaBody(BaseModel):
    task_id: int
    brand: BrandBody | None = None


class ReplicaBatchBody(BaseModel):
    content_ids: list[int] = Field(max_length=10)
    task_id: int
    brand: BrandBody | None = None


def _account_card(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "platform": row.platform,
        "account_key": row.account_key,
        "external_id": row.external_id,
        "nickname": row.nickname,
        "avatar_url": row.avatar_url,
        "follower_count": row.follower_count,
        "total_favorited": row.total_favorited,
        "content_count": row.content_count,
    }


def _task_stage(task: SocialTask, *, result_count: int) -> str:
    """probe 已在账号卡上；这里只区分 拉数入库 vs 结构分析。"""
    err = task.error or ""
    if task.status == "failed":
        return "failed"
    if task.status in ("pending", "running"):
        if err.startswith("[analyze_all]") or err.startswith("[retry_analyze_only]"):
            return "analyzing"
        if err.startswith("[fetch_only"):
            return "fetching"
        if (task.progress or 0) < 60:
            return "fetching"
        return "analyzing"
    if task.status == "done":
        if result_count == 0:
            return "fetched"
        return "analyzed"
    return "idle"


def _task_dict(
    task: SocialTask,
    *,
    hint: int | None = None,
    result_count: int = 0,
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": task.id,
        "tenant_id": task.tenant_id,
        "user_id": task.user_id,
        "platform": task.platform,
        "account_id": task.account_id,
        "status": task.status,
        "progress": task.progress,
        "total_count": task.total_count,
        "new_count": task.new_count,
        "skipped": task.skipped,
        "retry_count": task.retry_count,
        "error": task.error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "stage": _task_stage(task, result_count=result_count),
        "result_count": result_count,
    }
    if hint is not None:
        d["hint_previous_task_id"] = hint
    return d


def _raise_social(exc: Exception) -> None:
    if isinstance(exc, PlatformNotOpenError):
        raise HTTPException(
            status_code=501, detail={"code": "SOCIAL_PLATFORM", "message": str(exc)}
        )
    if isinstance(exc, TikHubRateLimitError):
        raise HTTPException(
            status_code=429, detail={"code": "SOCIAL_RATE", "message": str(exc)}
        )
    if isinstance(exc, SocialCostAlertError):
        raise HTTPException(
            status_code=402,
            detail={"code": "SOCIAL_COST_ALERT", "message": str(exc)},
        )
    if isinstance(exc, TikHubBalanceError):
        raise HTTPException(
            status_code=402,
            detail={
                "code": "SOCIAL_BALANCE",
                "message": str(exc),
                "topup_url": getattr(exc, "topup_url", None),
            },
        )
    if isinstance(exc, TikHubConfigError):
        raise HTTPException(
            status_code=503, detail={"code": "SOCIAL_CONFIG", "message": str(exc)}
        )
    if isinstance(exc, TikHubUpstreamError):
        raise HTTPException(
            status_code=502, detail={"code": "SOCIAL_UPSTREAM", "message": str(exc)}
        )
    raise exc


@router.get("/follows")
async def list_follows(
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    with _db_session() as session:
        rows = social_svc.list_followed_accounts(session, tenant_id=tenant.tenant_id)
        return {"items": [_account_card(r) for r in rows]}


@router.post("/probe")
async def probe(
    body: ProbeBody,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    with _db_session() as session:
        try:
            row = social_svc.probe_account(
                session,
                tenant_id=tenant.tenant_id,
                user_id=tenant.user_id,
                platform=body.platform,
                account_key=body.account_key,
            )
            session.commit()
            card = _account_card(row)
        except Exception as exc:
            session.rollback()
            _raise_social(exc)
            raise
    log_audit(
        background_tasks,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        action="social.probe",
        trace_id="",
        input_text=f"{body.platform}:{body.account_key}"[:200],
        output_text=str(card.get("nickname") or "")[:200],
    )
    return card


@router.post("/analysis-tasks")
async def create_task(
    body: TaskBody,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    created = False
    with _db_session() as session:
        try:
            task, created = social_svc.create_analysis_task(
                session,
                tenant_id=tenant.tenant_id,
                user_id=tenant.user_id,
                platform=body.platform,
                account_key=body.account_key,
                phase=body.phase,
                fetch_limit=body.fetch_limit,
            )
            session.commit()
            out = _task_dict(task)
            out["created"] = created
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            session.rollback()
            _raise_social(exc)
            raise
    if created:
        log_audit(
            background_tasks,
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            action="social.analysis.start",
            trace_id="",
            input_text=f"{body.platform}:{body.account_key}"[:200],
            output_text=str(out["id"]),
        )
    return out


@router.get("/analysis-tasks/{task_id}")
async def get_task(
    task_id: int,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    with _db_session() as session:
        task = (
            session.query(SocialTask)
            .filter(
                SocialTask.id == task_id,
                SocialTask.tenant_id == tenant.tenant_id,
            )
            .one_or_none()
        )
        if task is None:
            raise HTTPException(status_code=404, detail="task_not_found")
        hint = social_svc.hint_previous_task_id(session, task)
        results = (
            session.query(SocialResult)
            .filter(SocialResult.task_id == task_id)
            .all()
        )
        out = _task_dict(task, hint=hint, result_count=len(results))
        out["results"] = [
            {
                "content_id": r.content_id,
                "template_id": r.template_id,
                "structure_json": r.structure_json,
                "replica_json": r.replica_json,
            }
            for r in results
        ]
        return out


@router.post("/analysis-tasks/{task_id}/retry")
async def retry_task_endpoint(
    task_id: int,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    with _db_session() as session:
        task = (
            session.query(SocialTask)
            .filter(
                SocialTask.id == task_id,
                SocialTask.tenant_id == tenant.tenant_id,
            )
            .one_or_none()
        )
        if task is None:
            raise HTTPException(status_code=404, detail="task_not_found")
        try:
            social_svc.retry_task(session, task)
            session.commit()
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _task_dict(task)


@router.get("/contents")
async def list_contents(
    account_id: int = Query(...),
    like_min: int | None = None,
    collect_min: int | None = None,
    duration_min: int | None = None,
    duration_max: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    has_content: bool | None = None,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    del tenant  # global cache read; gate = account exists
    with _db_session() as session:
        rows = social_svc.list_contents(
            session,
            account_id=account_id,
            like_min=like_min,
            collect_min=collect_min,
            duration_min=duration_min,
            duration_max=duration_max,
            date_from=datetime.combine(date_from, datetime.min.time())
            if date_from
            else None,
            date_to=datetime.combine(date_to, datetime.max.time()) if date_to else None,
            has_content=has_content,
        )
        return {
            "items": [
                {
                    "id": r.id,
                    "platform": r.platform,
                    "account_id": r.account_id,
                    "external_id": r.external_id,
                    "title": r.title,
                    "content": r.content,
                    "content_source": r.content_source,
                    "duration_s": r.duration_s,
                    "like_count": r.like_count,
                    "comment_count": r.comment_count,
                    "share_count": r.share_count,
                    "collect_count": r.collect_count,
                    "published_at": r.published_at.isoformat()
                    if r.published_at
                    else None,
                    "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
                }
                for r in rows
            ]
        }


@router.get("/export/{task_id}.xlsx")
async def export_xlsx(
    task_id: int,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    with _db_session() as session:
        task = (
            session.query(SocialTask)
            .filter(
                SocialTask.id == task_id,
                SocialTask.tenant_id == tenant.tenant_id,
            )
            .one_or_none()
        )
        if task is None:
            raise HTTPException(status_code=404, detail="task_not_found")
        contents = (
            session.query(SocialContent)
            .filter(SocialContent.account_id == task.account_id)
            .order_by(SocialContent.published_at.desc())
            .all()
        )
        result_map = {
            r.content_id: r
            for r in session.query(SocialResult)
            .filter(SocialResult.task_id == task_id)
            .all()
        }
        rows = []
        for c in contents:
            res = result_map.get(c.id)
            rows.append(
                {
                    "platform": c.platform,
                    "title": c.title,
                    "content": c.content,
                    "external_id": c.external_id,
                    "duration_s": c.duration_s,
                    "like_count": c.like_count,
                    "comment_count": c.comment_count,
                    "share_count": c.share_count,
                    "collect_count": c.collect_count,
                    "published_at": c.published_at,
                    "fetched_at": c.fetched_at,
                    "content_source": c.content_source,
                    "replica_json": res.replica_json if res else None,
                }
            )
        data = build_analysis_xlsx(rows=rows, new_count=int(task.new_count or 0))
        n_rows = len(rows)
    log_audit(
        background_tasks,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        action="social.export",
        trace_id="",
        input_text=str(task_id),
        output_text=f"rows={n_rows}",
    )
    return Response(
        content=data,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="social_{task_id}.xlsx"'
        },
    )


@router.post("/contents/{content_id}/replica")
async def replica_one(
    content_id: int,
    body: ReplicaBody,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    with _db_session() as session:
        try:
            brand = social_svc.resolve_brand(
                session,
                tenant.tenant_id,
                body.brand.model_dump() if body.brand else None,
            )
            result = social_svc.stub_replica(
                session,
                tenant_id=tenant.tenant_id,
                user_id=tenant.user_id,
                content_id=content_id,
                task_id=body.task_id,
                brand=brand,
            )
            session.commit()
            payload = result.replica_json
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_audit(
        background_tasks,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        action="social.replica",
        trace_id="",
        input_text=f"content={content_id};task={body.task_id}",
        output_text="ok",
    )
    return {"content_id": content_id, "task_id": body.task_id, "replica": payload}


@router.post("/replica-batch")
async def replica_batch(
    body: ReplicaBatchBody,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    if not body.content_ids:
        raise HTTPException(status_code=400, detail="content_ids_required")
    if len(body.content_ids) > 10:
        raise HTTPException(status_code=400, detail="max_10")
    items = []
    with _db_session() as session:
        try:
            brand = social_svc.resolve_brand(
                session,
                tenant.tenant_id,
                body.brand.model_dump() if body.brand else None,
            )
            for cid in body.content_ids:
                result = social_svc.stub_replica(
                    session,
                    tenant_id=tenant.tenant_id,
                    user_id=tenant.user_id,
                    content_id=cid,
                    task_id=body.task_id,
                    brand=brand,
                )
                items.append({"content_id": cid, "replica": result.replica_json})
            session.commit()
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_audit(
        background_tasks,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        action="social.replica",
        trace_id="",
        input_text=f"batch={len(items)};task={body.task_id}",
        output_text="ok",
    )
    return {"items": items}


@router.get("/templates")
async def list_templates(
    platform: str | None = None,
    template_type: str | None = None,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    with _db_session() as session:
        q = session.query(SocialTemplate).filter(
            SocialTemplate.tenant_id == tenant.tenant_id
        )
        if platform:
            q = q.filter(SocialTemplate.platform == platform)
        if template_type:
            q = q.filter(SocialTemplate.template_type == template_type)
        rows = q.order_by(SocialTemplate.usage_count.desc()).limit(100).all()
        return {
            "items": [
                {
                    "id": r.id,
                    "platform": r.platform,
                    "template_key": r.template_key,
                    "template_type": r.template_type,
                    "sample_count": r.sample_count,
                    "usage_count": r.usage_count,
                    "structure_json": r.structure_json,
                }
                for r in rows
            ]
        }
