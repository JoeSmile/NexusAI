#!/usr/bin/env python3
"""
反馈相关路由 — 47b：upsert / mine / DELETE；租户隔离；bookmark 不进统计。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from packages.auth.models import TenantContext
from packages.auth.permissions import require_permission
from packages.auth.scope import require_tenant_admin
from backend.core.rate_limiter import check_endpoint_rate_limit
from backend.database import DatabaseManager
from backend.logging_config import get_logger
from backend.models import (
    FeedbackListResponse,
    FeedbackMineItem,
    FeedbackMineResponse,
    FeedbackRequest,
    FeedbackResponse,
    FeedbackStatistics,
)

router = APIRouter(
    prefix="/feedback",
    tags=["feedback"],
    dependencies=[Depends(require_permission("chat:write"))],
)
logger = get_logger(__name__)

ALLOWED_TYPES = frozenset(
    {"helpful", "irrelevant", "bookmark", "overstepping", "other"}
)
REACTION_TYPES = frozenset({"helpful", "irrelevant"})


def _normalize_rating(feedback_type: str, rating: int | None) -> int | None:
    if feedback_type == "bookmark":
        return None
    if feedback_type == "helpful":
        return 5 if rating is None else rating
    if feedback_type == "irrelevant":
        return 1 if rating is None else rating
    return rating


@router.post("/", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """提交用户反馈（user_id / tenant_id 只信服务端）。"""
    retry = check_endpoint_rate_limit(
        tenant.tenant_id, "feedback", limit_per_min=30
    )
    if retry is not None:
        raise HTTPException(
            status_code=429,
            detail="rate_limited",
            headers={"Retry-After": str(retry)},
        )
    ftype = (request.feedback_type or "").strip()
    if ftype not in ALLOWED_TYPES:
        raise HTTPException(status_code=422, detail="invalid_feedback_type")

    cid = (request.client_message_id or "").strip() or None
    if ftype in REACTION_TYPES | {"bookmark"} and not cid:
        raise HTTPException(status_code=422, detail="client_message_id_required")

    if ftype == "bookmark" and not (request.bot_response or "").strip():
        raise HTTPException(status_code=422, detail="bookmark_requires_bot_response")

    rating = _normalize_rating(ftype, request.rating)

    try:
        with DatabaseManager() as db:
            feedback = db.save_feedback(
                session_id=request.session_id,
                user_id=tenant.user_id,
                message_id=request.message_id,
                feedback_type=ftype,
                rating=rating,
                comment=request.comment or "",
                user_message=request.user_message or "",
                bot_response=request.bot_response or "",
                tenant_id=tenant.tenant_id,
                client_message_id=cid,
            )

            return FeedbackResponse(
            feedback_id=feedback.id,
            session_id=feedback.session_id,
            feedback_type=feedback.feedback_type,
            rating=feedback.rating,
            client_message_id=feedback.client_message_id,
            created_at=feedback.created_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交反馈错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mine", response_model=FeedbackMineResponse)
async def list_my_feedback(
    feedback_type: str | None = Query(None, alias="type"),
    session_id: str | None = None,
    limit: int = Query(50, ge=1, le=50),
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """当前用户本租户反馈（hydrate / 收藏列表）。"""
    try:
        with DatabaseManager() as db:
            items, total = db.list_my_feedback(
                tenant_id=tenant.tenant_id,
                user_id=tenant.user_id,
                feedback_type=feedback_type,
                session_id=session_id,
                limit=limit,
            )
            return FeedbackMineResponse(
                items=[
                    FeedbackMineItem(
                        id=f.id,
                        session_id=f.session_id,
                        client_message_id=f.client_message_id,
                        feedback_type=f.feedback_type,
                        rating=f.rating,
                        comment=f.comment,
                        user_message=f.user_message,
                        bot_response=f.bot_response,
                        created_at=f.created_at.isoformat() if f.created_at else None,
                    )
                    for f in items
                ],
                total=total,
            )
    except Exception as e:
        logger.error(f"拉取本人反馈错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/mine/{feedback_id}", status_code=204)
async def delete_my_feedback(
    feedback_id: int,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """取消赞/踩/收藏；非本人或跨租户 → 404。切片 4 再挂 warm 删除。"""
    try:
        with DatabaseManager() as db:
            ok = db.delete_feedback_owned(
                feedback_id=feedback_id,
                tenant_id=tenant.tenant_id,
                user_id=tenant.user_id,
            )
            if not ok:
                raise HTTPException(status_code=404, detail="not_found")
            return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除反馈错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics", response_model=FeedbackStatistics)
async def get_feedback_statistics(
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """获取反馈统计信息（admin；排除 bookmark）。"""
    require_tenant_admin(tenant)
    try:
        with DatabaseManager() as db:
            stats = db.get_feedback_statistics(tenant_id=tenant.tenant_id)
            return FeedbackStatistics(**stats)
    except Exception as e:
        logger.error(f"获取反馈统计错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", response_model=FeedbackListResponse)
async def get_feedback_list(
    feedback_type: str | None = None,
    limit: int = 100,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """获取反馈列表（admin；本租户）。"""
    require_tenant_admin(tenant)
    try:
        with DatabaseManager() as db:
            feedbacks = db.get_all_feedback(
                feedback_type=feedback_type,
                limit=limit,
                tenant_id=tenant.tenant_id,
            )

            feedback_list = [
                {
                    "id": f.id,
                    "tenant_id": f.tenant_id,
                    "session_id": f.session_id,
                    "user_id": f.user_id,
                    "message_id": f.message_id,
                    "client_message_id": f.client_message_id,
                    "feedback_type": f.feedback_type,
                    "rating": f.rating,
                    "comment": f.comment,
                    "user_message": f.user_message,
                    "bot_response": f.bot_response,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                    "is_resolved": f.is_resolved,
                }
                for f in feedbacks
            ]

            return FeedbackListResponse(
                feedbacks=feedback_list, total=len(feedback_list)
            )
    except Exception as e:
        logger.error(f"获取反馈列表错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}")
async def get_session_feedback(
    session_id: str,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """获取特定会话的反馈（tenant_admin / super_admin）。"""
    require_tenant_admin(tenant)
    try:
        with DatabaseManager() as db:
            feedbacks = db.get_feedback_by_session(
                session_id, tenant_id=tenant.tenant_id
            )

            return {
                "session_id": session_id,
                "feedbacks": [
                    {
                        "id": f.id,
                        "feedback_type": f.feedback_type,
                        "rating": f.rating,
                        "comment": f.comment,
                        "created_at": f.created_at.isoformat()
                        if f.created_at
                        else None,
                    }
                    for f in feedbacks
                ],
            }
    except Exception as e:
        logger.error(f"获取会话反馈错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{feedback_id}/resolve")
async def resolve_feedback(
    feedback_id: int,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """标记反馈已解决（admin）"""
    require_tenant_admin(tenant)
    try:
        with DatabaseManager() as db:
            feedback = db.mark_feedback_resolved(feedback_id)
            if not feedback:
                raise HTTPException(status_code=404, detail="反馈不存在")

            return {
                "message": "反馈已标记为已解决",
                "feedback_id": feedback_id,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"标记反馈已解决错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))
