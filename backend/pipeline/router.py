"""FastAPI → LangGraph 转接层 — 管线入口"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.core.audit import log_audit
from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_permission
from backend.core.errors import ContextGateException
from backend.core.guardrails.output_guard import DRIFT_PATTERNS, VIOLATION_PATTERNS
from backend.observability.decorators import observe
from backend.pipeline.graph import compiled_graph
from backend.pipeline.state import make_initial_state

router = APIRouter(tags=["chat"])

_STREAM_FILTER = re.compile(
    "|".join(VIOLATION_PATTERNS + DRIFT_PATTERNS),
    re.IGNORECASE,
)


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    user_id: str = "anonymous"


class ChatResponse(BaseModel):
    response: str
    trace_id: str
    finish_reason: str
    total_tokens: int
    total_cost: float
    pipeline_latency_ms: float
    approval_request_id: str | None = None
    error_code: str | None = None


@router.post("/chat", response_model=ChatResponse)
@observe(name="chat.pipeline")
async def chat_pipeline(
    request: Request,
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """处理聊天请求 — 走 LangGraph 管线"""
    start = time.time()

    initial = make_initial_state(
        tenant_id=tenant.tenant_id,
        user_id=body.user_id or tenant.user_id,
        session_id=body.session_id,
        message=body.message,
        user_context={
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id,
            "permissions": tenant.extra_permissions,
            "role": tenant.role,
        },
        trace_id=getattr(request.state, "trace_id", None),
    )

    try:
        final = await compiled_graph.ainvoke(initial)
        latency = (time.time() - start) * 1000
        final["pipeline_latency_ms"] = latency

        log_audit(
            background_tasks,
            tenant_id=final["tenant_id"],
            user_id=final["user_id"],
            action="chat",
            trace_id=final["trace_id"],
            input_text=final["message"],
            output_text=final["response"],
            model=final.get("selected_model", ""),
            input_tokens=len(final["message"]),
            output_tokens=len(final.get("response") or ""),
            cost=final.get("total_cost", 0.0),
            latency_ms=latency,
            error_code=final.get("error_code"),
            ip_address=request.client.host if request.client else "",
            user_agent=request.headers.get("User-Agent", ""),
        )

        return ChatResponse(
            response=final["response"],
            trace_id=final["trace_id"],
            finish_reason=final["finish_reason"],
            total_tokens=final["total_tokens"],
            total_cost=final["total_cost"],
            pipeline_latency_ms=latency,
            approval_request_id=final.get("approval_request_id"),
            error_code=final.get("error_code"),
        )

    except ContextGateException:
        raise
    except Exception as e:
        latency = (time.time() - start) * 1000
        return ChatResponse(
            response=f"系统错误: {str(e)}",
            trace_id=initial["trace_id"],
            finish_reason="error",
            total_tokens=0,
            total_cost=0.0,
            pipeline_latency_ms=latency,
            error_code="SYS_001",
        )


@router.post("/chat/streaming")
async def chat_streaming(
    request: Request,
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """
    SSE 骨架（04.11）+ abort/retraction（09.04）。
    长路径假 token 流；完整 Harness stream 见 07.07e。
    """
    initial = make_initial_state(
        tenant_id=tenant.tenant_id,
        user_id=body.user_id or tenant.user_id,
        session_id=body.session_id,
        message=body.message,
        user_context={
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id,
            "permissions": tenant.extra_permissions,
            "role": tenant.role,
        },
        trace_id=getattr(request.state, "trace_id", None),
    )

    final = await compiled_graph.ainvoke(initial)
    if final.get("finish_reason") in ("skill_executed", "cache_hit", "blocked"):
        return JSONResponse({"response": final.get("response", "")})

    text = final.get("response") or ""

    async def event_stream() -> AsyncIterator[str]:
        buffer = ""
        for ch in text:
            buffer += ch
            if _STREAM_FILTER.search(buffer):
                yield (
                    "data: "
                    + json.dumps(
                        {"type": "abort", "reason": "content_filter"},
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"
                return
            yield (
                "data: "
                + json.dumps({"token": ch}, ensure_ascii=False)
                + "\n\n"
            )

        if len(buffer) > 4000:
            yield (
                "data: "
                + json.dumps(
                    {"type": "retraction", "reason": "length_exceeded"},
                    ensure_ascii=False,
                )
                + "\n\n"
            )
        background_tasks.add_task(lambda: None)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
