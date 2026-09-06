"""FastAPI → LangGraph 转接层 — 管线入口"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from packages.audit import log_audit
from packages.audit_context import bind_audit_lineage
from packages.auth.models import TenantContext
from packages.auth.permissions import require_permission
from packages.billing.context import bind_billing_context
from packages.errors import ErrorCode, NexusAIException
from packages.observability.decorators import observe
from packages.pipeline.graph import compiled_graph
from packages.pipeline.state import make_initial_state
from packages.plan.event_bus import (
    event_to_sse_payload,
    get_run_bus,
    get_run_bus_optional,
)
from packages.plan.run_cancel import (
    clear_cancel,
    is_cancelled,
    register_run,
    unregister_run,
)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    # deprecated: ignored — identity comes from TenantContext only
    user_id: str | None = None
    # Homepage context panel: optional registry model id
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=16, le=8192)
    # 47b I1 — FE bubble UUIDs (persisted on write_memory)
    user_client_message_id: str | None = None
    assistant_client_message_id: str | None = None
    # Task 63 — component interaction callback (e.g. hotspot_table → script.gen)
    render_action: dict[str, Any] | None = None


def _apply_render_action_message(body: ChatRequest) -> str:
    """Turn structured component callbacks into a planner-friendly user message."""
    base = (body.message or "").strip()
    ra = body.render_action
    if not isinstance(ra, dict) or not ra:
        return body.message
    action = str(ra.get("action") or "")
    if action == "script.gen":
        hotspots = ra.get("hotspots")
        if not isinstance(hotspots, list):
            payload = ra.get("payload")
            hotspots = payload.get("hotspots") if isinstance(payload, dict) else []
        if isinstance(hotspots, list) and hotspots:
            blob = json.dumps(hotspots[:20], ensure_ascii=False)
            prefix = base or "请为以下热点生成口播脚本"
            return f"{prefix}\n{blob}"
    return body.message


def _bind_chat_request_to_state(body: ChatRequest, initial: dict) -> None:
    message = _apply_render_action_message(body)
    if message != body.message:
        initial["message"] = message
        initial["raw_input"] = message
    if body.render_action:
        initial["render_action"] = body.render_action


def _render_from_final(final: dict) -> RenderDirectiveOut | None:
    raw = final.get("render_directive")
    if not isinstance(raw, dict) or not raw.get("component"):
        return None
    return RenderDirectiveOut(
        component=str(raw["component"]),
        payload=dict(raw.get("payload") or {}),
    )


def _require_chat_model(body: ChatRequest) -> None:
    """Legacy sync guard — prefer ``_resolve_chat_model`` in route handlers."""
    if not (body.model or "").strip():
        raise NexusAIException(
            ErrorCode.LLM_MODEL_REQUIRED.value,
            "model_required",
            detail="Pick a model in the UI",
        )


async def _resolve_chat_model(body: ChatRequest, tenant_id: str) -> None:
    from packages.llm_credentials import resolve_chat_model_for_request

    body.model = await resolve_chat_model_for_request(tenant_id, body.model)


def _enforce_terms(request: Request, tenant: TenantContext) -> None:
    from packages.terms.service import enforce_terms_for_chat

    enforce_terms_for_chat(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        credential_kind="company",
        ip_address=request.client.host if request.client else None,
    )


class RenderDirectiveOut(BaseModel):
    component: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    response: str
    trace_id: str
    finish_reason: str
    total_tokens: int
    total_cost: float
    pipeline_latency_ms: float
    approval_request_id: str | None = None
    error_code: str | None = None
    render: RenderDirectiveOut | None = None


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
    from packages.observability.decorators import enrich_span, langfuse_context
    from packages.observability.langfuse_client import (
        discard_langfuse_buffer,
        flush_langfuse,
    )
    from packages.observability.sampling import (
        is_short_path,
        reset_sampling_state,
        should_sample,
        tracing_enabled,
    )

    reset_sampling_state(enabled=True)
    start = time.time()
    finish_reason = "error"

    await _resolve_chat_model(body, tenant.tenant_id)
    _enforce_terms(request, tenant)

    initial = make_initial_state(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        session_id=body.session_id,
        message=body.message,
        user_context={
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id,
            "permissions": tenant.extra_permissions,
            "role": tenant.role,
        },
        trace_id=getattr(request.state, "trace_id", None),
        preferred_model=body.model,
        user_client_message_id=body.user_client_message_id,
        assistant_client_message_id=body.assistant_client_message_id,
        llm_temperature=body.temperature,
        llm_max_tokens=body.max_tokens,
    )
    _bind_chat_request_to_state(body, initial)
    bind_audit_lineage(trace_id=initial["trace_id"])
    bind_billing_context(user_id=tenant.user_id, trace_id=initial["trace_id"])
    _inject_langfuse_parent(initial)
    trace_id = initial["trace_id"]
    register_run(trace_id)

    try:
        final = await compiled_graph.ainvoke(initial)
        latency = (time.time() - start) * 1000
        final["pipeline_latency_ms"] = latency
        finish_reason = final.get("finish_reason") or "llm_generated"

        audit_input = str(final.get("raw_input") or final.get("message") or "")
        if len(audit_input) > 4000:
            audit_input = audit_input[:4000]

        log_audit(
            background_tasks,
            tenant_id=final["tenant_id"],
            user_id=final["user_id"],
            action="chat",
            trace_id=final["trace_id"],
            input_text=audit_input,
            output_text=final["response"],
            model=final.get("selected_model", ""),
            input_tokens=len(audit_input),
            output_tokens=len(final.get("response") or ""),
            cost=final.get("total_cost", 0.0),
            latency_ms=latency,
            error_code=final.get("error_code"),
            ip_address=request.client.host if request.client else "",
            user_agent=request.headers.get("User-Agent", ""),
            intent_predicted=final.get("intent"),
            intent_confidence=final.get("intent_confidence"),
            intent_source=final.get("intent_source"),
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
            render=_render_from_final(final),
        )

    except NexusAIException:
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
        unregister_run(trace_id)
        clear_cancel(trace_id)
        # 与 model_router 短路径降采样共用同一决策（should_sample 幂等）
        keep = should_sample(finish_reason) and tracing_enabled()
        if keep:
            background_tasks.add_task(flush_langfuse)
        else:
            background_tasks.add_task(discard_langfuse_buffer)


def _inject_langfuse_parent(initial: Any) -> None:
    """把当前 Langfuse 根 span id 注入 state,让 LangGraph 节点挂成其子 span(GAP-08)。"""
    try:
        from packages.observability.decorators import langfuse_context

        tid = langfuse_context.get_current_trace_id()
        oid = langfuse_context.get_current_observation_id()
        if tid and oid:
            initial["_lf_trace_id"] = tid
            initial["_lf_parent_obs_id"] = oid
    except Exception:
        pass


@observe(name="chat.pipeline.streaming")
async def _ainvoke_streaming(initial: Any) -> Any:
    """streaming 入口: 建立根 trace,避免节点 span 变孤儿根 trace(GAP-08)。"""
    _inject_langfuse_parent(initial)
    return await compiled_graph.ainvoke(initial)


def _sse_data(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def _execution_snapshot(trace_id: str | None) -> dict | None:
    bus = get_run_bus_optional(trace_id)
    if bus is None:
        return None
    return bus.snapshot_dict()


def _sse_buffered_execution_events(trace_id: str | None) -> list[str]:
    bus = get_run_bus_optional(trace_id)
    if bus is None:
        return []
    return [
        _sse_data(event_to_sse_payload(ev))
        for ev in bus.events_all()
    ]


def _cache_meta(final: dict) -> dict:
    """SSE / JSON cache badge fields (Task 80.2). Only exact|template, not semantic."""
    if final.get("finish_reason") != "cache_hit":
        return {}
    ctype = final.get("cache_type")
    if ctype not in ("exact", "template"):
        return {}
    return {"cache_hit": True, "cache_type": ctype}


def _chat_json_payload(final: dict) -> dict:
    payload: dict = {
        "response": final.get("response", ""),
        "trace_id": final.get("trace_id"),
        "finish_reason": final.get("finish_reason"),
    }
    payload.update(_cache_meta(final))
    snap = _execution_snapshot(final.get("trace_id"))
    if snap is not None:
        payload["execution_snapshot"] = snap
    render = _render_from_final(final)
    if render is not None:
        payload["render"] = render.model_dump(mode="json")
    clarification = final.get("clarification")
    if isinstance(clarification, dict) and clarification:
        payload["clarification"] = clarification
    if final.get("finish_reason") == "command_result":
        payload["type"] = "command_result"
        cmd = final.get("command")
        if cmd:
            payload["command"] = cmd
    return payload


def _sse_done_payload(final: dict) -> dict:
    """Typed SSE done frame — finish_reason 透传（Task 72 D7）。"""
    payload: dict = {
        "type": "done",
        "finish_reason": final.get("finish_reason") or "llm_generated",
        "trace_id": final.get("trace_id"),
    }
    payload.update(_cache_meta(final))
    snap = _execution_snapshot(final.get("trace_id"))
    if snap is not None:
        payload["execution_snapshot"] = snap
    render = _render_from_final(final)
    if render is not None:
        payload["render"] = render.model_dump(mode="json")
    clarification = final.get("clarification")
    if isinstance(clarification, dict) and clarification:
        payload["clarification"] = clarification
    return payload


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

    await _resolve_chat_model(body, tenant.tenant_id)
    _enforce_terms(request, tenant)

    initial = make_initial_state(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        session_id=body.session_id,
        message=body.message,
        user_context={
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id,
            "permissions": tenant.extra_permissions,
            "role": tenant.role,
        },
        trace_id=getattr(request.state, "trace_id", None),
        preferred_model=body.model,
        user_client_message_id=body.user_client_message_id,
        assistant_client_message_id=body.assistant_client_message_id,
        llm_temperature=body.temperature,
        llm_max_tokens=body.max_tokens,
    )
    _bind_chat_request_to_state(body, initial)
    initial["stream_mode"] = True
    bind_audit_lineage(trace_id=initial["trace_id"])
    bind_billing_context(user_id=tenant.user_id, trace_id=initial["trace_id"])
    _inject_langfuse_parent(initial)
    trace_id = initial["trace_id"]
    register_run(trace_id)

    def _release_run() -> None:
        unregister_run(trace_id)
        clear_cancel(trace_id)

    try:
        final = await _ainvoke_streaming(initial)
    except NexusAIException as e:
        _release_run()
        return JSONResponse(
            status_code=400,
            content={
                "type": "error",
                "code": getattr(e, "code", "SYS_001"),
                "message": getattr(e, "message", None) or "请求失败，请稍后重试。",
            },
        )
    except Exception:
        _release_run()
        return JSONResponse(
            status_code=500,
            content={
                "type": "error",
                "code": "SYS_001",
                "message": "请求失败，请稍后重试。",
            },
        )

    if final.get("error_code"):
        _release_run()
        return JSONResponse(
            status_code=400,
            content={
                "type": "error",
                "code": final.get("error_code"),
                "message": final.get("response") or "request_failed",
            },
        )
    if final.get("finish_reason") != "routed_to_llm":
        _release_run()
        return JSONResponse(_chat_json_payload(final))

    from packages.billing.context import bind_billing_from_pipeline_state
    from packages.harness import LLMHarness
    from packages.pipeline.context_messages import build_llm_messages
    from packages.pipeline.nodes.conversion_hook import conversion_hook
    from packages.pipeline.nodes.llm_generate import _resolve_system_template
    from packages.pipeline.nodes.write_memory import write_memory

    bind_billing_from_pipeline_state(final)
    harness = LLMHarness()
    model = final.get("selected_model") or "deepseek-v4-flash"
    system_template, _prompt_meta = await _resolve_system_template(final)
    stream_messages = build_llm_messages(final, system_template=system_template)

    async def event_stream() -> AsyncIterator[str]:
        nonlocal final, stream_messages

        from packages.pipeline.nodes.task_plan import (
            run_async_task_plan_for_stream,
            should_async_plan_on_stream,
        )

        # 复杂任务默认异步规划（简单路径不进）；ASYNC_TASK_PLAN_ON_STREAM=1 仍为全开调试。
        if should_async_plan_on_stream(final):
            tid = str(final.get("trace_id") or "")
            bus = get_run_bus(tid) if tid else None
            pending_seq = 0
            if bus is not None:
                pending = bus.publish_task_plan_pending(
                    message=str(final.get("message") or "")[:200]
                )
                pending_seq = pending.seq
                yield _sse_data(event_to_sse_payload(pending))

            final, _plan_status = await run_async_task_plan_for_stream(
                final, emit_pending=False
            )
            if bus is not None:
                for ev in bus.events_since(pending_seq):
                    yield _sse_data(event_to_sse_payload(ev))

            # 编排已产出终态：不再走 LLM token 流
            fr = final.get("finish_reason")
            if fr and fr not in ("routed_to_llm",):
                try:
                    if fr == "clarification_pending":
                        clarify = final.get("clarification") or {}
                        yield _sse_data({"type": "clarify", **clarify})
                        await write_memory(final)
                    else:
                        text = str(final.get("response") or "")
                        if text:
                            yield _sse_data({"token": text})
                        await write_memory(final)
                        await conversion_hook(final)
                    yield _sse_data(_sse_done_payload(final))
                    yield "data: [DONE]\n\n"
                finally:
                    _release_run()
                return

            # 降级/超时后继续直答：刷新 messages（可能带上 query_rewrite）
            system_template2, _ = await _resolve_system_template(final)
            stream_messages = build_llm_messages(
                final, system_template=system_template2
            )
        else:
            for line in _sse_buffered_execution_events(final.get("trace_id")):
                yield line

        from packages.audit import write_audit_sync
        from packages.guardrails.generation_exit import resolve_output_guard_profile
        from packages.guardrails.stream_guard import (
            apply_stream_block_to_state,
            remaining_pending,
            sanitize_streaming_chunk,
            stream_block_audit_record,
            student_names_from_warm,
        )

        stream_profile = resolve_output_guard_profile(str(final.get("tenant_id") or ""))
        stream_names = student_names_from_warm(final.get("warm_memory") or {})
        emitted = ""
        unsent = ""
        token_iter = harness.stream(
            model=model,
            messages=stream_messages,
            tenant_id=final["tenant_id"],
            api_key=final.get("llm_api_key") or "",
            base_url=final.get("llm_base_url") or "",
            provider=final.get("llm_key_provider") or "default",
            max_tokens=final.get("llm_max_tokens"),
            temperature=final.get("llm_temperature")
            if final.get("llm_temperature") is not None
            else 0.7,
            key_id=final.get("llm_key_id"),
        )

        try:
            while True:
                if is_cancelled(final.get("trace_id")):
                    logger.info("SSE cancelled via DELETE — stop generation")
                    yield _sse_data({"type": "cancelled", "reason": "user_request"})
                    yield "data: [DONE]\n\n"
                    return
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

                unsent += tok
                delta, reason = sanitize_streaming_chunk(
                    clean_so_far=emitted,
                    new_chunk=unsent,
                    tenant_id=str(final.get("tenant_id") or ""),
                    profile=stream_profile,
                    names=stream_names,
                    max_chars=4000,
                )
                next_unsent = remaining_pending(emitted, unsent, stream_names)
                if reason.startswith("blocked"):
                    yield _sse_data({"type": "abort", "reason": "content_filter"})
                    apply_stream_block_to_state(final, reason=reason)
                    try:
                        write_audit_sync(
                            stream_block_audit_record(
                                final, reason=reason, profile=stream_profile
                            )
                        )
                    except Exception:
                        logger.debug("stream_block audit skipped", exc_info=True)
                    await write_memory(final)
                    await conversion_hook(final)
                    yield _sse_data(_sse_done_payload(final))
                    yield "data: [DONE]\n\n"
                    return
                if delta:
                    yield _sse_data({"token": delta})
                    emitted += delta
                if reason == "length_retracted":
                    yield _sse_data({"type": "retraction", "reason": "length_exceeded"})
                    unsent = ""
                    break
                unsent = next_unsent

            if not emitted and await request.is_disconnected():
                return

            if emitted:
                final["response"] = emitted
                final["finish_reason"] = harness.stream_finish_reason()
                await write_memory(final)
                # SSE 长路径: 图在 conversion_hook 处已结束(stream_mode),此处补记转化。
                await conversion_hook(final)
            yield _sse_data(_sse_done_payload(final))
            yield "data: [DONE]\n\n"

        except asyncio.CancelledError:
            logger.info("SSE cancelled — abort LLM stream")
            raise
        except NexusAIException as e:
            if e.message == "llm_slot_busy":
                yield _sse_data(
                    {
                        "type": "error",
                        "code": e.code,
                        "message": "llm_slot_busy",
                        "retry_after": 2,
                    }
                )
            else:
                logger.exception("SSE stream error: %s", e)
                yield _sse_data(
                    {
                        "type": "error",
                        "code": e.code or "LLM_002",
                        "message": "生成失败，请稍后重试或换个说法。",
                    }
                )
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.exception("SSE stream error: %s", e)
            # 08-25 脱敏：不把 LLM 原始输出/内部细节发给前端（曾泄漏 rewrite 内容给用户）
            # 错误详情进日志与审计，SSE 只给安全文案；code 保留供前端分类
            yield _sse_data(
                {
                    "type": "error",
                    "code": "LLM_002",
                    "message": "生成失败，请稍后重试或换个说法。",
                }
            )
            yield "data: [DONE]\n\n"
        finally:
            await token_iter.aclose()
            _release_run()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
