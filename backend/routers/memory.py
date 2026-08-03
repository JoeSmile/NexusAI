#!/usr/bin/env python3
"""记忆系统相关路由 — 鉴权 + 租户/用户作用域（防 IDOR）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_permission
from backend.core.auth.scope import assert_user_access, require_tenant_admin
from backend.logging_config import get_logger
from backend.services.context_service import ContextService
from backend.services.memory_service import MemoryService

router = APIRouter(
    prefix="/memory",
    tags=["memory"],
    dependencies=[Depends(require_permission("chat:write"))],
)
logger = get_logger(__name__)


class MemoryImportanceUpdate(BaseModel):
    importance: float = Field(..., ge=0.0, le=1.0)


def _services(tenant: TenantContext) -> tuple[MemoryService, ContextService]:
    ms = MemoryService(tenant_id=tenant.tenant_id)
    return ms, ContextService(memory_service=ms)


# 兼容旧单测名
_require_memory_admin = require_tenant_admin


@router.get("/users/{user_id}/memories")
async def get_user_memories(
    user_id: str,
    memory_type: str | None = None,
    limit: int = 50,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    uid = assert_user_access(tenant, user_id)
    ms, _ = _services(tenant)
    try:
        memories = await ms.get_user_memories_list(
            user_id=uid, memory_type=memory_type, limit=limit
        )
        return {
            "user_id": uid,
            "memories": memories,
            "total": len(memories),
            "type_filter": memory_type,
            "tenant_id": tenant.tenant_id,
        }
    except Exception as e:
        logger.error(f"获取用户记忆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/{user_id}/memories/important")
async def get_important_memories(
    user_id: str,
    limit: int = 5,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    uid = assert_user_access(tenant, user_id)
    ms, _ = _services(tenant)
    try:
        memories = await ms.get_important_memories(uid, limit)
        return {
            "user_id": uid,
            "important_memories": memories,
            "total": len(memories),
        }
    except Exception as e:
        logger.error(f"获取重要记忆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/{user_id}/memories/search")
async def search_memories(
    user_id: str,
    query: str,
    n_results: int = 3,
    days_limit: int = 7,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    _ = days_limit
    uid = assert_user_access(tenant, user_id)
    ms, _ = _services(tenant)
    try:
        memories = await ms.retrieve_memories(
            user_id=uid, query=query, limit=n_results
        )
        return {
            "user_id": uid,
            "query": query,
            "memories": memories,
            "total": len(memories),
        }
    except Exception as e:
        logger.error(f"搜索记忆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/users/{user_id}/memories/{memory_id}")
async def delete_memory(
    user_id: str,
    memory_id: str,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    uid = assert_user_access(tenant, user_id)
    ms, _ = _services(tenant)
    try:
        success = await ms.delete_memory(uid, memory_id)
        if not success:
            raise HTTPException(status_code=404, detail="记忆不存在")
        return {"message": "记忆删除成功", "memory_id": memory_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除记忆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/users/{user_id}/memories")
async def forget_user_memories(
    user_id: str,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """被遗忘权：仅 tenant_admin / super_admin；作用域为调用方租户。"""
    require_tenant_admin(tenant)
    uid = assert_user_access(tenant, user_id)
    ms, _ = _services(tenant)
    try:
        result = await ms.forget_user(uid)
        return {
            "message": "用户记忆已清除",
            "tenant_id": tenant.tenant_id,
            **result,
        }
    except Exception as e:
        logger.error(f"遗忘权清除失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.patch("/users/{user_id}/memories/{memory_id}/importance")
async def update_memory_importance(
    user_id: str,
    memory_id: str,
    request: MemoryImportanceUpdate,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    uid = assert_user_access(tenant, user_id)
    ms, _ = _services(tenant)
    try:
        success = await ms.update_memory_importance(
            user_id=uid,
            memory_id=memory_id,
            new_importance=request.importance,
        )
        if not success:
            raise HTTPException(status_code=404, detail="记忆不存在或更新失败")
        return {
            "message": "记忆重要性更新成功",
            "memory_id": memory_id,
            "importance": request.importance,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新记忆重要性失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/{user_id}/statistics")
async def get_memory_statistics(
    user_id: str,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    uid = assert_user_access(tenant, user_id)
    ms, _ = _services(tenant)
    try:
        stats = await ms.get_memory_statistics(uid)
        return {"user_id": uid, "statistics": stats}
    except Exception as e:
        logger.error(f"获取记忆统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/{user_id}/profile")
async def get_user_profile(
    user_id: str,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    uid = assert_user_access(tenant, user_id)
    _, cs = _services(tenant)
    try:
        profile = await cs.get_user_profile(uid)
        return {"user_id": uid, "profile": profile.to_dict()}
    except Exception as e:
        logger.error(f"获取用户画像失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/users/{user_id}/profile")
async def update_user_profile(
    user_id: str,
    updates: dict,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    uid = assert_user_access(tenant, user_id)
    _, cs = _services(tenant)
    try:
        profile = await cs.update_user_profile(uid, updates)
        return {
            "message": "用户画像更新成功",
            "user_id": uid,
            "profile": profile.to_dict(),
        }
    except Exception as e:
        logger.error(f"更新用户画像失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
