"""
Agent Router - Agent路由

.. deprecated::
    对话真源是 ``POST /chat/streaming``。Hub ``kind=agent`` 只编排子工具，
    不再走 AgentService 聊天。本路由仅保留 status/tools/history/memory/followup 兼容。
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from packages.auth.models import TenantContext
from packages.auth.permissions import require_permission
from packages.auth.scope import assert_user_access, resolve_acting_user_id
from packages.errors import raise_internal_error
from packages.services.agent_service import AgentService, get_agent_service

router = APIRouter(prefix="/agent", tags=["agent"])

_SUCCESSOR = "/chat/streaming"
_DEP_TRUE = "true"


def _dep_headers() -> dict[str, str]:
    return {
        "Deprecation": _DEP_TRUE,
        "Link": f'<{_SUCCESSOR}>; rel="successor-version"',
    }


def _stamp(response: Response) -> None:
    for k, v in _dep_headers().items():
        response.headers[k] = v


# ==================== 请求模型 ====================

class FollowupRequest(BaseModel):
    """回访请求"""
    user_id: str = ""


# ==================== API端点 ====================

@router.get("/status", deprecated=True)
async def get_agent_status(
    http_request: Request,
    response: Response,
    agent_service: AgentService = Depends(get_agent_service),
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """Agent状态（deprecated → ``GET /api/agents``）。"""
    _stamp(response)
    try:
        status = agent_service.get_agent_status()

        return {
            "code": 200,
            "message": "success",
            "data": status
        }

    except Exception as e:
        raise_internal_error(http_request, e)


@router.get("/history/{user_id}", deprecated=True)
async def get_execution_history(
    user_id: str,
    http_request: Request,
    response: Response,
    limit: int = 10,
    agent_service: AgentService = Depends(get_agent_service),
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """执行历史（deprecated；非 admin 仅可查本人）。"""
    _stamp(response)
    assert_user_access(tenant, user_id)
    try:
        history = agent_service.get_execution_history(user_id, limit)

        return {
            "code": 200,
            "message": "success",
            "data": history
        }

    except Exception as e:
        raise_internal_error(http_request, e)


@router.get("/memory/{user_id}", deprecated=True)
async def get_memory_summary(
    user_id: str,
    http_request: Request,
    response: Response,
    agent_service: AgentService = Depends(get_agent_service),
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """记忆摘要（deprecated → ``/memory/...``；非 admin 仅可查本人）。"""
    _stamp(response)
    assert_user_access(tenant, user_id)
    try:
        summary = await agent_service.get_memory_summary(user_id)

        return {
            "code": 200,
            "message": "success",
            "data": summary
        }

    except Exception as e:
        raise_internal_error(http_request, e)


@router.get("/tools", deprecated=True)
async def get_available_tools(
    http_request: Request,
    response: Response,
    agent_service: AgentService = Depends(get_agent_service),
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """可用工具列表（deprecated → ``GET /api/agents`` / capabilities）。"""
    _stamp(response)
    try:
        tools = agent_service.get_available_tools()

        return {
            "code": 200,
            "message": "success",
            "data": tools
        }

    except Exception as e:
        raise_internal_error(http_request, e)


@router.post("/followup", deprecated=True)
async def plan_followup(
    request: FollowupRequest,
    http_request: Request,
    response: Response,
    agent_service: AgentService = Depends(get_agent_service),
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """回访规划（deprecated；body.user_id 仅 admin 可覆写）。"""
    _stamp(response)
    try:
        uid = resolve_acting_user_id(tenant, request.user_id)
        followup = await agent_service.schedule_followup(uid)

        if followup:
            return {
                "code": 200,
                "message": "已创建回访计划",
                "data": followup
            }
        else:
            return {
                "code": 200,
                "message": "暂无回访需求",
                "data": None
            }

    except HTTPException:
        raise
    except Exception as e:
        raise_internal_error(http_request, e)


@router.get("/health", deprecated=True)
async def health_check(response: Response):
    """健康检查（deprecated → ``GET /health``）。"""
    _stamp(response)
    return {
        "code": 200,
        "message": "Agent服务运行正常",
        "data": {
            "status": "healthy",
            "version": "1.0.0",
            "deprecated": True,
        }
    }
