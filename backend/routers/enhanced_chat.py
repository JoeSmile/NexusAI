#!/usr/bin/env python3
"""已废弃——多轮对话/记忆请走 ``POST /chat``（LangGraph）与 ``/memory/*``、``/agent/*``。

``/enhanced-chat/*`` 仅兼容保留；物理删除见 Task 32+（能力化收口）。
已知缺口：``GET /users/{uid}/sessions``（会话列表）无 1:1 主入口对等——
会话列表能力并入 Capability Hub 规划（Task 32+），本任务不补。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response

from backend.logging_config import get_logger
from backend.models import ChatRequest, ChatResponse
from backend.services.enhanced_chat_service import EnhancedChatService

router = APIRouter(prefix="/enhanced-chat", tags=["增强版聊天"])
logger = get_logger(__name__)

enhanced_chat_service = EnhancedChatService(
    use_rag=True,
    use_intent=True,
    use_enhanced_processor=True,
)


def _stamp(response: Response, successor: str) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = f'<{successor}>; rel="successor-version"'


@router.post("/", response_model=ChatResponse, deprecated=True)
async def enhanced_chat(request: ChatRequest, response: Response):
    """增强版聊天（deprecated → ``POST /chat``）。"""
    try:
        result = await enhanced_chat_service.chat(request)
        _stamp(response, "/chat")
        return result
    except Exception as e:
        logger.error(f"增强版聊天接口错误: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/sessions/{session_id}/history", deprecated=True)
async def get_session_history(
    session_id: str, response: Response, limit: int = 20
) -> dict[str, Any]:
    """会话历史（deprecated → ``/agent/history`` + ``/memory/.../memories``）。"""
    try:
        history = await enhanced_chat_service.get_session_history(session_id, limit)
        _stamp(response, "/agent/history/{user_id}")
        if not history.get("messages"):
            return {"session_id": session_id, "messages": []}
        return history
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话历史错误: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/{user_id}/sessions", deprecated=True)
async def get_user_sessions(
    user_id: str, response: Response, limit: int = 50
) -> Any:
    """用户会话列表（deprecated；无 1:1 主入口——见模块 docstring）。"""
    try:
        sessions = await enhanced_chat_service.get_user_sessions(user_id, limit)
        _stamp(response, "/memory/users/{user_id}/statistics")
        return sessions
    except Exception as e:
        logger.error(f"获取用户会话列表错误: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/sessions/{session_id}", deprecated=True)
async def delete_session(session_id: str, response: Response) -> dict[str, str]:
    """删除会话（deprecated → ``DELETE /memory/users/{uid}/memories/{id}``）。"""
    try:
        success = await enhanced_chat_service.delete_session(session_id)

        if not success:
            raise HTTPException(status_code=404, detail="会话不存在")

        _stamp(response, "/memory/users/{user_id}/memories/{memory_id}")
        return {"message": "会话删除成功", "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话错误: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/{user_id}/profile", deprecated=True)
async def get_user_profile(user_id: str, response: Response) -> Any:
    """用户画像（deprecated → ``GET /memory/users/{uid}/profile``）。"""
    try:
        profile = await enhanced_chat_service.get_user_profile(user_id)
        _stamp(response, "/memory/users/{user_id}/profile")
        return profile
    except Exception as e:
        logger.error(f"获取用户画像错误: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/users/{user_id}/memories", deprecated=True)
async def get_user_memories(
    user_id: str, response: Response, limit: int = 10
) -> dict[str, Any]:
    """用户记忆（deprecated → ``GET /memory/users/{uid}/memories``）。"""
    try:
        memories = await enhanced_chat_service.get_user_memories(user_id, limit)
        _stamp(response, "/memory/users/{user_id}/memories")
        return {"user_id": user_id, "memories": memories, "total": len(memories)}
    except Exception as e:
        logger.error(f"获取用户记忆错误: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/system/status", deprecated=True)
async def get_system_status(response: Response) -> dict[str, Any]:
    """系统状态（deprecated → ``GET /health`` / ``/system/info``）。"""
    _stamp(response, "/health")
    return {
        "version": "enhanced_v1.0",
        "features": {
            "enhanced_memory": {
                "enabled": True,
                "description": "短期滑动窗口 + 长期向量检索 + 时间衰减",
            },
            "user_profile": {
                "enabled": True,
                "description": "动态用户画像构建",
            },
            "rag": {
                "enabled": enhanced_chat_service.rag_enabled,
                "description": "RAG知识库增强",
            },
            "intent_recognition": {
                "enabled": enhanced_chat_service.intent_enabled,
                "description": "意图识别系统",
            },
            "input_processor": {
                "enabled": enhanced_chat_service.enhanced_processor_enabled,
                "description": "增强版输入处理",
            },
        },
        "status": "operational",
    }
