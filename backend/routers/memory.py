#!/usr/bin/env python3
"""
记忆系统相关路由
"""


from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.auth.api_key_auth import verify_api_key
from backend.core.auth.models import TenantContext
from backend.logging_config import get_logger
from backend.services.context_service import ContextService
from backend.services.memory_service import MemoryService

router = APIRouter(prefix="/memory", tags=["memory"])
logger = get_logger(__name__)

# 初始化服务
memory_service = MemoryService()
context_service = ContextService(memory_service=memory_service)


class MemoryImportanceUpdate(BaseModel):
    importance: float = Field(..., ge=0.0, le=1.0)


def _require_memory_admin(tenant: TenantContext) -> TenantContext:
    """遗忘权等破坏性操作：仅 tenant_admin / super_admin。"""
    if tenant.role not in ("tenant_admin", "super_admin"):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "AUTH_002",
                "message": "insufficient_permissions",
                "hint": "forget_requires_tenant_admin_or_super_admin",
            },
        )
    return tenant


@router.get("/users/{user_id}/memories")
async def get_user_memories(
    user_id: str,
    memory_type: str | None = None,
    limit: int = 50
):
    """
    获取用户记忆列表
    
    Args:
        user_id: 用户ID
        memory_type: 记忆类型（event/relationship/commitment/preference/concern）
        limit: 返回数量限制
    """
    try:
        memories = await memory_service.get_user_memories_list(
            user_id=user_id,
            memory_type=memory_type,
            limit=limit
        )
        
        return {
            "user_id": user_id,
            "memories": memories,
            "total": len(memories),
            "type_filter": memory_type
        }
    except Exception as e:
        logger.error(f"获取用户记忆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/memories/important")
async def get_important_memories(user_id: str, limit: int = 5):
    """
    获取用户最重要的记忆
    
    Args:
        user_id: 用户ID
        limit: 返回数量限制
    """
    try:
        memories = await memory_service.get_important_memories(user_id, limit)
        
        return {
            "user_id": user_id,
            "important_memories": memories,
            "total": len(memories)
        }
    except Exception as e:
        logger.error(f"获取重要记忆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/memories/search")
async def search_memories(
    user_id: str,
    query: str,
    n_results: int = 3,
    days_limit: int = 7
):
    """
    搜索相关记忆
    
    Args:
        user_id: 用户ID
        query: 搜索查询
        n_results: 返回数量
        days_limit: 时间限制（天数）
    """
    try:
        memories = await memory_service.retrieve_memories(
            user_id=user_id,
            query=query,
            limit=n_results,
        )
        
        return {
            "user_id": user_id,
            "query": query,
            "memories": memories,
            "total": len(memories)
        }
    except Exception as e:
        logger.error(f"搜索记忆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{user_id}/memories/{memory_id}")
async def delete_memory(user_id: str, memory_id: str):
    """
    删除指定记忆
    
    Args:
        user_id: 用户ID
        memory_id: 记忆ID
    """
    try:
        success = await memory_service.delete_memory(user_id, memory_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="记忆不存在")
        
        return {
            "message": "记忆删除成功",
            "memory_id": memory_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除记忆失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{user_id}/memories")
async def forget_user_memories(
    user_id: str,
    tenant: TenantContext = Depends(verify_api_key),
):
    """被遗忘权：删 warm/cold + 脱敏 chat_messages。仅 tenant_admin / super_admin，作用域为调用方租户。"""
    _require_memory_admin(tenant)
    try:
        scoped = MemoryService(tenant_id=tenant.tenant_id)
        result = await scoped.forget_user(user_id)
        return {
            "message": "用户记忆已清除",
            "tenant_id": tenant.tenant_id,
            **result,
        }
    except Exception as e:
        logger.error(f"遗忘权清除失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/users/{user_id}/memories/{memory_id}/importance")
async def update_memory_importance(
    user_id: str,
    memory_id: str,
    request: MemoryImportanceUpdate,
):
    """Update a user-owned memory's importance score."""
    try:
        success = await memory_service.update_memory_importance(
            user_id=user_id,
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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/statistics")
async def get_memory_statistics(user_id: str):
    """
    获取记忆统计信息
    
    Args:
        user_id: 用户ID
    """
    try:
        stats = await memory_service.get_memory_statistics(user_id)
        
        return {
            "user_id": user_id,
            "statistics": stats
        }
    except Exception as e:
        logger.error(f"获取记忆统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/profile")
async def get_user_profile(user_id: str):
    """
    获取用户画像
    
    Args:
        user_id: 用户ID
    """
    try:
        profile = await context_service.get_user_profile(user_id)
        
        return {
            "user_id": user_id,
            "profile": profile.to_dict()
        }
    except Exception as e:
        logger.error(f"获取用户画像失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/users/{user_id}/profile")
async def update_user_profile(user_id: str, updates: dict):
    """
    更新用户画像
    
    Args:
        user_id: 用户ID
        updates: 更新的字段
    """
    try:
        profile = await context_service.update_user_profile(user_id, updates)
        
        return {
            "message": "用户画像更新成功",
            "user_id": user_id,
            "profile": profile.to_dict()
        }
    except Exception as e:
        logger.error(f"更新用户画像失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
