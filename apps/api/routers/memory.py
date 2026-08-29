#!/usr/bin/env python3
"""记忆系统相关路由 — 鉴权 + 租户/用户作用域；读写经 UnifiedMemoryService。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from packages.audit import log_audit
from packages.memory.memory_service import get_unified_memory_service
from packages.logging_config import get_logger
from packages.services.context_service import ContextService
from packages.auth.models import TenantContext
from packages.auth.permissions import require_permission
from packages.auth.scope import assert_user_access, require_tenant_admin

router = APIRouter(
    prefix="/memory",
    tags=["memory"],
    dependencies=[Depends(require_permission("chat:write"))],
)
logger = get_logger(__name__)


class MemoryImportanceUpdate(BaseModel):
    importance: float = Field(..., ge=0.0, le=1.0)


class MemoryValueUpdate(BaseModel):
    value: str = Field(..., min_length=1, max_length=8000)


def _mem(tenant: TenantContext):
    return get_unified_memory_service(tenant_id=tenant.tenant_id)


def _context() -> ContextService:
    return ContextService()


# 兼容旧单测名
_require_memory_admin = require_tenant_admin


@router.get("/me/memories")
async def get_my_memories(
    memory_type: str | None = None,
    limit: int = Query(200, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """Current user's warm memories (47b slice 3)."""
    memories = await _mem(tenant).list_warm(
        tenant.user_id, memory_type=memory_type, limit=limit
    )
    return {
        "user_id": tenant.user_id,
        "memories": memories,
        "total": len(memories),
        "tenant_id": tenant.tenant_id,
    }


@router.patch("/me/memories/{memory_id}")
async def patch_my_memory(
    memory_id: str,
    request: MemoryValueUpdate,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    ok = await _mem(tenant).update_warm_value(
        tenant.user_id, memory_id, request.value
    )
    if not ok:
        raise HTTPException(status_code=404, detail="记忆不存在")
    log_audit(
        background_tasks,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        action="memory.update",
        trace_id="",
        input_text=memory_id,
    )
    return {"message": "记忆已更新", "memory_id": memory_id}


@router.delete("/me/memories/{memory_id}")
async def delete_my_memory(
    memory_id: str,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    ok = await _mem(tenant).delete_warm(
        user_id=tenant.user_id, memory_id=memory_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="记忆不存在")
    log_audit(
        background_tasks,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        action="memory.delete",
        trace_id="",
        input_text=memory_id,
    )
    return {"message": "记忆删除成功", "memory_id": memory_id}


@router.get("/users/{user_id}/memories")
async def get_user_memories(
    user_id: str,
    memory_type: str | None = None,
    limit: int = 50,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    uid = assert_user_access(tenant, user_id)
    try:
        memories = await _mem(tenant).list_warm(
            uid, memory_type=memory_type, limit=limit
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
    try:
        memories = await _mem(tenant).list_important_warm(uid, limit=limit)
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
    try:
        memories = await _mem(tenant).search_warm(
            uid, query, limit=n_results
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
    try:
        success = await _mem(tenant).delete_warm(user_id=uid, memory_id=memory_id)
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
    try:
        result = await _mem(tenant).forget_user(uid)
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
    try:
        success = await _mem(tenant).update_warm_importance(
            uid, memory_id, request.importance
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
    try:
        stats = await _mem(tenant).warm_statistics(uid)
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
    try:
        profile = await _context().get_user_profile(uid)
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
    try:
        profile = await _context().update_user_profile(uid, updates)
        return {
            "message": "用户画像更新成功",
            "user_id": uid,
            "profile": profile.to_dict(),
        }
    except Exception as e:
        logger.error(f"更新用户画像失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
