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
async def chat_pipeline(
    request: Request,
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """处理聊天请求 — 走 LangGraph 管线"""
    # 注意: 不能把 @observe 直接挂在 FastAPI 路由上（会破坏签名/Depends）
    return await _run_chat_pipeline(request, body, background_tasks, tenant)


@observe(name="chat.pipeline")
async def _run_chat_pipeline(
    request: Request,
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    tenant: TenantContext,
):
    from backend.observability.decorators import enrich_span, langfuse_context
    from backend.observability.langfuse_client import (
        discard_langfuse_buffer,
        flush_langfuse,
    )
    from backend.observability.sampling import (
        is_short_path,
        set_tracing_enabled,
        should_sample,
    )

    set_tracing_enabled(True)
    start = time.time()
    finish_reason = "error"

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
        finish_reason = final.get("finish_reason") or "llm_generated"

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

        enrich_span(
            input_data={"message": final.get("message"), "trace_id": final.get("trace_id")},
            output_data={
                "finish_reason": finish_reason,
                "model": final.get("selected_model"),
                "total_cost": final.get("total_cost"),
            },
            metadata={
                "path": "short" if is_short_path(finish_reason) else "long",
                "ab_experiment_id": final.get("ab_experiment_id"),
                "ab_variant": final.get("ab_variant"),
            },
        )
        try:
            langfuse_context.update_current_trace(  # type: ignore[attr-defined]
                metadata={
                    "trace_id": final.get("trace_id"),
                    "path": "short" if is_short_path(finish_reason) else "long",
                }
            )
        except Exception:
            pass

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
        finish_reason = "error"
        return ChatResponse(
            response=f"系统错误: {e!s}",
            trace_id=initial["trace_id"],
            finish_reason="error",
            total_tokens=0,
            total_cost=0.0,
            pipeline_latency_ms=latency,
            error_code="SYS_001",
        )
    finally:
        if should_sample(finish_reason):
            background_tasks.add_task(flush_langfuse)
        else:
            background_tasks.add_task(discard_langfuse_buffer)



def _sse_data(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


@router.post("/chat/streaming")
async def chat_streaming(
    request: Request,
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """
    SSE（04.11）+ abort/retraction（09.04）+ LLMHarness.stream（07.07e）。
    短路径 JSON；长路径真流式。支持 15s 心跳、客户端断开中止、统一 error 事件。
    注意: Last-Event-ID 断点续传尚未实现。
    """
    import asyncio
    import logging

    logger = logging.getLogger(__name__)

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
    initial["stream_mode"] = True

    try:
        final = await compiled_graph.ainvoke(initial)
    except ContextGateException as e:
        return JSONResponse(
            status_code=400,
            content={
                "type": "error",
                "code": getattr(e, "code", "SYS_001"),
                "message": str(e),
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "type": "error",
                "code": "SYS_001",
                "message": str(e),
            },
        )

    if final.get("finish_reason") in (
        "skill_executed",
        "cache_hit",
        "blocked",
        "PENDING_APPROVAL",
        "AUTH_002",
    ):
        return JSONResponse({"response": final.get("response", "")})

    from backend.core.harness import LLMHarness
    from backend.pipeline.nodes.write_memory import write_memory

    harness = LLMHarness()
    model = final.get("selected_model") or "deepseek-chat"
    prompt = final.get("raw_input") or final.get("message") or ""

    async def event_stream() -> AsyncIterator[str]:
        buffer = ""
        token_iter = harness.stream(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            tenant_id=final["tenant_id"],
            api_key=final.get("llm_api_key") or "",
            base_url=final.get("llm_base_url") or "",
        ).__aiter__()

        try:
            while True:
                if await request.is_disconnected():
                    logger.info("SSE client disconnected — stop generation")
                    break
                try:
                    tok = await asyncio.wait_for(token_iter.__anext__(), timeout=15.0)
                except StopAsyncIteration:
                    break
                except TimeoutError:
                    yield ": ping\n\n"
                    continue

                buffer += tok
                if _STREAM_FILTER.search(buffer):
                    yield _sse_data({"type": "abort", "reason": "content_filter"})
                    yield "data: [DONE]\n\n"
                    return
                yield _sse_data({"token": tok})

            if not buffer and await request.is_disconnected():
                return

            if len(buffer) > 4000:
                yield _sse_data({"type": "retraction", "reason": "length_exceeded"})
                buffer = buffer[:4000]

            if buffer:
                final["response"] = buffer
                final["finish_reason"] = "llm_generated"
                await write_memory(final)
            yield "data: [DONE]\n\n"

        except asyncio.CancelledError:
            logger.info("SSE cancelled — abort LLM stream")
            raise
        except Exception as e:
            logger.exception("SSE stream error: %s", e)
            yield _sse_data(
                {
                    "type": "error",
                    "code": "LLM_002",
                    "message": str(e),
                }
            )
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
