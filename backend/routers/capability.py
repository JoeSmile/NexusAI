"""Capability Hub API — 市场列表 + 统一 invoke（Task 30.06）。

LangFuse 根 trace / SSE 组帧 / 断连中止在本层；core 只做纯分发。
长路径：``@observe`` 包住 async generator，span 贯穿整段 SSE。

鉴权例外（见 AGENTS.md）: ``Depends(verify_api_key)`` + 每能力
``spec.permission`` / 租户可见性，不用固定 ``@require_permission``。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.core.audit import log_audit
from backend.core.auth.api_key_auth import verify_api_key
from backend.core.auth.models import TenantContext
from backend.core.capability.invoke import invoke
from backend.core.capability.models import CapabilitySpec
from backend.core.capability.registry import get_capability_registry
from backend.core.errors import ContextGateException
from backend.observability.decorators import observe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])


class InvokeRequest(BaseModel):
    message: str | None = None
    input: str | None = None
    query: str | None = None
    messages: list[dict[str, Any]] | None = None
    max_tokens: int | None = None
    stream: bool | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


def _sse_data(payload: dict[str, Any]) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _spec_public(spec: CapabilitySpec) -> dict[str, Any]:
    return {
        "id": spec.id,
        "name": spec.name,
        "kind": spec.kind.value,
        "provider": spec.provider.value,
        "status": spec.status.value,
        "permission": spec.permission or "chat:write",
        "tenant_id": spec.tenant_id,
        "cost_model": dict(spec.cost_model or {}),
        "spec": {
            k: v
            for k, v in (spec.spec or {}).items()
            if k not in ("api_key", "api_key_ref", "headers", "secrets")
        },
    }


def _visible_to(tenant: TenantContext, spec: CapabilitySpec) -> bool:
    from backend.core.capability.invoke import capability_visible_to

    return capability_visible_to(spec, tenant)


def _wants_stream(
    request: Request, body_stream: bool | None, q_stream: bool | None
) -> bool:
    if q_stream is not None:
        return q_stream
    if body_stream is not None:
        return body_stream
    accept = (request.headers.get("accept") or "").lower()
    if "text/event-stream" in accept:
        return True
    if "application/json" in accept and "text/event-stream" not in accept:
        return False
    return True


def _payload_from_body(body: InvokeRequest) -> dict[str, Any]:
    payload: dict[str, Any] = dict(body.extra or {})
    if body.messages is not None:
        payload["messages"] = body.messages
    if body.message is not None:
        payload["message"] = body.message
    if body.input is not None:
        payload["input"] = body.input
    if body.query is not None:
        payload["query"] = body.query
    if body.max_tokens is not None:
        payload["max_tokens"] = body.max_tokens
    return payload


def _frame_to_sse(frame: dict[str, Any]) -> str:
    """将 invoke 事件字典转为 /chat/streaming 兼容 SSE 行。"""
    ev = frame.get("event")
    data = frame.get("data")
    if ev == "token":
        out: dict[str, Any] = {"token": data}
        if "cost_source" in frame:
            out["cost_source"] = frame["cost_source"]
        return _sse_data(out)
    if ev == "done":
        meta = data if isinstance(data, dict) else {"data": data}
        if "cost_source" in frame:
            meta = {**meta, "cost_source": frame["cost_source"]}
        return _sse_data({"type": "done", **meta}) + "data: [DONE]\n\n"
    if ev == "error":
        return _sse_data(
            {
                "type": "error",
                "code": (data or {}).get("code")
                if isinstance(data, dict)
                else "SYS_001",
                "message": (data or {}).get("message")
                if isinstance(data, dict)
                else str(data),
            }
        )
    payload = {"type": ev or "event", "data": data}
    if "cost_source" in frame:
        payload["cost_source"] = frame["cost_source"]
    return _sse_data(payload)


def _schedule_audit(
    background_tasks: BackgroundTasks,
    *,
    tenant: TenantContext,
    request: Request,
    capability_id: str,
    cost_source: str,
    input_text: str,
    output_text: str,
    latency_ms: float,
    error_code: str | None = None,
    upstream: str | None = None,
) -> None:
    tags = f"[cost_source={cost_source}]"
    if upstream:
        tags += f"[upstream={upstream}]"
    prefixed = f"{tags} {input_text}".strip()
    log_audit(
        background_tasks,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        action="capability.invoke",
        trace_id=str(getattr(request.state, "trace_id", "") or ""),
        input_text=prefixed[:4000],
        output_text=(output_text or "")[:4000],
        model=capability_id,
        latency_ms=latency_ms,
        error_code=error_code,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", "")[:256],
    )


def _schedule_langfuse_flush(
    background_tasks: BackgroundTasks, *, short_path: bool
) -> None:
    from backend.observability.langfuse_client import (
        discard_langfuse_buffer,
        flush_langfuse,
    )
    from backend.observability.sampling import should_sample, tracing_enabled

    finish = "skill_executed" if short_path else "llm_generated"
    keep = should_sample(finish) and tracing_enabled()
    if keep:
        background_tasks.add_task(flush_langfuse)
    else:
        background_tasks.add_task(discard_langfuse_buffer)


def _preflight(cap_id: str, tenant: TenantContext) -> CapabilitySpec:
    """在返回 StreamingResponse 前暴露 CAP_/AUTH_（JSON 错误，非 SSE）。"""
    from backend.core.capability.governance import (
        check_cap_quota,
        check_cap_rate_limit,
    )
    from backend.core.capability.invoke import _check_permission

    spec = get_capability_registry().get(cap_id)
    _check_permission(spec, tenant)
    check_cap_rate_limit(tenant.tenant_id)
    check_cap_quota(tenant.tenant_id)
    return spec


@router.get("")
@router.get("/")
async def list_capabilities(
    kind: str | None = Query(None),
    provider: str | None = Query(None),
    include_disabled: bool = Query(False),
    tenant: TenantContext = Depends(verify_api_key),
):
    """能力市场列表 — 按角色权限 + 租户范围过滤可见性。"""
    reg = get_capability_registry()
    specs = reg.list(
        kind=kind,
        provider=provider,
        include_disabled=include_disabled,
    )
    if include_disabled and not (
        tenant.is_cross_tenant or tenant.has_permission("admin:*")
    ):
        specs = reg.list(kind=kind, provider=provider, include_disabled=False)

    items = [_spec_public(s) for s in specs if _visible_to(tenant, s)]
    return {"items": items, "total": len(items)}


@observe(name="capability.invoke")
async def _invoke_short(
    cap_id: str,
    payload: dict[str, Any],
    tenant: TenantContext,
) -> tuple[str, str, dict[str, Any], str | None]:
    """短路径：聚合 token → (response, cost_source, done_meta, upstream)。"""
    chunks: list[str] = []
    cost_source = "harness"
    done_meta: dict[str, Any] = {}
    upstream: str | None = None
    async for frame in invoke(cap_id, payload, tenant):
        if frame.get("event") == "token":
            chunks.append(str(frame.get("data") or ""))
        if frame.get("cost_source"):
            cost_source = str(frame["cost_source"])
        data = frame.get("data")
        if (
            frame.get("event") == "usage"
            and isinstance(data, dict)
            and data.get("upstream")
        ):
            upstream = str(data["upstream"])
        if frame.get("event") == "done" and isinstance(data, dict):
            done_meta = data
            if data.get("upstream"):
                upstream = str(data["upstream"])
    return "".join(chunks), cost_source, done_meta, upstream


@observe(name="capability.invoke.streaming")
async def _sse_event_stream(
    *,
    cap_id: str,
    payload: dict[str, Any],
    tenant: TenantContext,
    request: Request,
    background_tasks: BackgroundTasks,
    input_preview: str,
    t0: float,
) -> AsyncIterator[str]:
    """长路径 SSE — observe span 保持到 generator 耗尽。"""
    buffer = ""
    cost_source = "harness"
    upstream: str | None = None
    error_code: str | None = None
    token_iter = invoke(cap_id, payload, tenant).__aiter__()

    try:
        while True:
            if await request.is_disconnected():
                logger.info("capability SSE client disconnected — stop")
                break
            try:
                frame = await asyncio.wait_for(token_iter.__anext__(), timeout=15.0)
            except StopAsyncIteration:
                break
            except TimeoutError:
                yield ": ping\n\n"
                continue

            if frame.get("cost_source"):
                cost_source = str(frame["cost_source"])
            data = frame.get("data")
            if isinstance(data, dict) and data.get("upstream"):
                upstream = str(data["upstream"])
            if frame.get("event") == "token":
                buffer += str(frame.get("data") or "")
            yield _frame_to_sse(frame)
            if frame.get("event") == "done":
                break

    except asyncio.CancelledError:
        logger.info("capability SSE cancelled")
        raise
    except ContextGateException as e:
        error_code = getattr(e, "code", "SYS_001")
        yield _sse_data({"type": "error", "code": error_code, "message": str(e)})
        yield "data: [DONE]\n\n"
    except Exception as e:
        logger.exception("capability SSE error: %s", e)
        error_code = "SYS_001"
        yield _sse_data({"type": "error", "code": "SYS_001", "message": str(e)})
        yield "data: [DONE]\n\n"
    finally:
        latency = (time.perf_counter() - t0) * 1000
        if buffer or error_code:
            _schedule_audit(
                background_tasks,
                tenant=tenant,
                request=request,
                capability_id=cap_id,
                cost_source=cost_source,
                input_text=input_preview,
                output_text=buffer,
                latency_ms=latency,
                error_code=error_code,
                upstream=upstream,
            )
        _schedule_langfuse_flush(background_tasks, short_path=False)


@router.post("/{cap_id}/invoke")
async def invoke_capability(
    cap_id: str,
    request: Request,
    body: InvokeRequest,
    background_tasks: BackgroundTasks,
    stream: bool | None = Query(None),
    tenant: TenantContext = Depends(verify_api_key),
):
    """
    统一 invoke：长路径 SSE（复用 /chat/streaming 事件格式）+ 短路径 JSON。
    支持 15s `: ping` 心跳、客户端断开中止、审计 cost_source。
    """
    payload = _payload_from_body(body)
    wants_stream = _wants_stream(request, body.stream, stream)
    t0 = time.perf_counter()
    input_preview = str(
        payload.get("message")
        or payload.get("input")
        or payload.get("query")
        or ""
    )[:500]

    if not wants_stream:
        try:
            text, cost_source, done_meta, upstream = await _invoke_short(
                cap_id, payload, tenant
            )
        except ContextGateException:
            _schedule_langfuse_flush(background_tasks, short_path=True)
            raise
        except Exception as e:
            _schedule_langfuse_flush(background_tasks, short_path=True)
            raise ContextGateException("SYS_001", str(e)) from e

        latency = (time.perf_counter() - t0) * 1000
        _schedule_audit(
            background_tasks,
            tenant=tenant,
            request=request,
            capability_id=cap_id,
            cost_source=cost_source,
            input_text=input_preview,
            output_text=text,
            latency_ms=latency,
            upstream=upstream,
        )
        _schedule_langfuse_flush(background_tasks, short_path=True)
        return {
            "response": text,
            "capability_id": cap_id,
            "kind": done_meta.get("kind"),
            "cost_source": cost_source,
            "upstream": upstream,
            "finish_reason": "completed",
        }

    # 预检失败 → 全局异常处理器 JSON；通过后 SSE span 覆盖整段流
    try:
        _preflight(cap_id, tenant)
    except ContextGateException:
        _schedule_langfuse_flush(background_tasks, short_path=False)
        raise

    return StreamingResponse(
        _sse_event_stream(
            cap_id=cap_id,
            payload=payload,
            tenant=tenant,
            request=request,
            background_tasks=background_tasks,
            input_preview=input_preview,
            t0=t0,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = ["router"]
