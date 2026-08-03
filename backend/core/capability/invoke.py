"""Capability invoke 核心分发（Task 30.04 / 30b）。

分层约束: 本模块禁止 import ``backend.pipeline``。
SSE 组帧 / LangFuse 根注入在 routers 层（30.06）。

成本幂等: kind=model 由 harness 内部 ``record_consumption``;
external_app / agent 由本层记账并带 ``cost_source: invoke``。
kind=tool 经 ``spec.executor`` 映射到 model / rag（Task 30b）。
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from backend.core.auth.models import TenantContext
from backend.core.capability.errors import (
    CapabilityNotFoundError,
    CapabilityUpstreamError,
)
from backend.core.capability.models import CapabilityKind, CapabilitySpec
from backend.core.capability.registry import (
    get_capability_registry,
    resolve_credential,
)
from backend.core.errors import ContextGateException, ErrorCode

logger = logging.getLogger(__name__)

# tool 叶子 executor → 真实执行器（不按 capability id 硬编码）
_TOOL_EXECUTOR_MODEL = frozenset({"model", "chat", "llm"})
_TOOL_EXECUTOR_RAG = frozenset({"rag", "rag_ask", "rag-ask"})


def _messages_from_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    msgs = payload.get("messages")
    if isinstance(msgs, list) and msgs:
        out: list[dict[str, str]] = []
        for m in msgs:
            if isinstance(m, dict) and m.get("content") is not None:
                out.append(
                    {
                        "role": str(m.get("role") or "user"),
                        "content": str(m["content"]),
                    }
                )
        if out:
            return out
    text = payload.get("message") or payload.get("input") or payload.get("query")
    if text:
        return [{"role": "user", "content": str(text)}]
    return []


def _check_permission(spec: CapabilitySpec, tenant: TenantContext) -> None:
    needed = (spec.permission or "").strip() or "chat:write"
    if not tenant.has_permission(needed):
        raise ContextGateException(
            ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS.value,
            "insufficient_permissions",
            detail=needed,
        )


async def _invoke_model(
    spec: CapabilitySpec,
    payload: dict[str, Any],
    tenant: TenantContext,
) -> AsyncIterator[dict[str, Any]]:
    from backend.core.harness import LLMHarness

    messages = _messages_from_payload(payload)
    if not messages:
        raise ContextGateException(
            ErrorCode.REQ_INVALID.value,
            "invalid_payload",
            detail="messages_or_message_required",
        )

    model_name = str(spec.spec.get("model") or spec.name)
    api_key_ref = str(spec.spec.get("api_key_ref") or "")
    api_key = resolve_credential(api_key_ref, tenant_id=tenant.tenant_id) or None
    base_url = str(spec.spec.get("base_url") or "") or None
    max_tokens = int(spec.spec.get("max_tokens") or payload.get("max_tokens") or 1000)

    harness = LLMHarness()
    # kind=model: 不在此调用 record_consumption（harness.stream 内部已记）
    async for token in harness.stream(
        model=model_name,
        messages=messages,
        tenant_id=tenant.tenant_id,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
    ):
        yield {"event": "token", "data": token, "cost_source": "harness"}

    yield {
        "event": "done",
        "data": {"capability_id": spec.id, "kind": spec.kind.value},
        "cost_source": "harness",
    }


async def _invoke_external_app(
    spec: CapabilitySpec,
    payload: dict[str, Any],
    tenant: TenantContext,
) -> AsyncIterator[dict[str, Any]]:
    """占位：完整转发在 30.07 连接器实现。"""
    try:
        from backend.core.capability import connectors  # type: ignore[attr-defined]
    except ImportError:
        connectors = None

    if connectors is None or not hasattr(connectors, "invoke_external"):
        raise CapabilityUpstreamError(
            message="connector_not_ready",
            detail=f"{spec.provider.value}:await_30.07",
        )

    cost = 0.0
    tokens = 0
    async for frame in connectors.invoke_external(spec, payload, tenant):
        if frame.get("event") == "usage":
            cost = float((frame.get("data") or {}).get("cost") or 0)
            tokens = int((frame.get("data") or {}).get("tokens") or 0)
        yield {**frame, "cost_source": "invoke"}

    if cost or tokens:
        from backend.core.cost_manager import record_consumption

        # 审计带 cost_source 由 30.06 router 写入 BackgroundTasks
        record_consumption(tenant.tenant_id, cost, tokens, model=spec.id)


async def _invoke_agent(
    spec: CapabilitySpec,
    payload: dict[str, Any],
    tenant: TenantContext,
) -> AsyncIterator[dict[str, Any]]:
    """Agent 门面分发（``backend.core.capability.agents``）。"""
    from backend.core.capability import agents as agent_runtime

    cost = 0.0
    tokens = 0
    async for frame in agent_runtime.invoke_agent(spec, payload, tenant):
        if frame.get("event") == "usage":
            cost = float((frame.get("data") or {}).get("cost") or 0)
            tokens = int((frame.get("data") or {}).get("tokens") or 0)
        yield {**frame, "cost_source": "invoke"}

    if cost or tokens:
        from backend.core.cost_manager import record_consumption

        record_consumption(tenant.tenant_id, cost, tokens, model=spec.id)


async def _invoke_rag(
    spec: CapabilitySpec,
    payload: dict[str, Any],
    tenant: TenantContext,
) -> AsyncIterator[dict[str, Any]]:
    """tool/rag：与 ``POST /api/rag/ask`` 同源的 ``RAGService.ask``。"""
    from backend.modules.rag.routers.rag_router import get_rag_service

    messages = _messages_from_payload(payload)
    if not messages:
        raise ContextGateException(
            ErrorCode.REQ_INVALID.value,
            "invalid_payload",
            detail="messages_or_message_required",
        )
    question = messages[-1]["content"]
    search_k = int(payload.get("search_k") or spec.spec.get("search_k") or 3)

    try:
        result = get_rag_service().ask(
            question=question,
            search_k=search_k,
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id or "anonymous",
        )
    except ContextGateException:
        raise
    except Exception as exc:
        logger.exception("rag tool invoke failed: %s", spec.id)
        raise CapabilityUpstreamError(
            message="rag_ask_failed",
            detail=f"{spec.id}:{exc}",
        ) from exc

    answer = str((result or {}).get("answer") or "")
    # 粗分片，保持与 model / stub 一致的 token 流形态
    chunk = 24
    for i in range(0, max(len(answer), 1), chunk):
        part = answer[i : i + chunk] if answer else ""
        if part:
            yield {"event": "token", "data": part, "cost_source": "invoke"}

    cost = 0.0
    try:
        cost = float((result or {}).get("cost") or 0)
    except (TypeError, ValueError):
        cost = 0.0
    if cost:
        from backend.core.cost_manager import record_consumption

        record_consumption(tenant.tenant_id, cost, max(1, len(answer) // 4), model=spec.id)
        yield {
            "event": "usage",
            "data": {"cost": cost, "tokens": max(1, len(answer) // 4)},
            "cost_source": "invoke",
        }

    yield {
        "event": "done",
        "data": {
            "capability_id": spec.id,
            "kind": spec.kind.value,
            "executor": "rag",
            "knowledge_count": (result or {}).get("knowledge_count"),
            "cache_hit": (result or {}).get("cache_hit"),
        },
        "cost_source": "invoke",
    }


async def _invoke_tool(
    spec: CapabilitySpec,
    payload: dict[str, Any],
    tenant: TenantContext,
) -> AsyncIterator[dict[str, Any]]:
    """按 ``spec.executor`` 路由 tool 叶子（Task 30b）。"""
    executor = str((spec.spec or {}).get("executor") or "").strip().lower()
    if executor in _TOOL_EXECUTOR_MODEL:
        raw = dict(spec.spec or {})
        if not raw.get("model"):
            raw["model"] = (os.getenv("LLM_MODEL") or "").strip() or "mock-local"
        model_spec = replace(spec, spec=raw)
        async for frame in _invoke_model(model_spec, payload, tenant):
            yield frame
        return
    if executor in _TOOL_EXECUTOR_RAG:
        async for frame in _invoke_rag(spec, payload, tenant):
            yield frame
        return
    raise CapabilityNotFoundError(
        message="unsupported_kind",
        detail=f"{spec.id}:{spec.kind.value}:executor={executor or 'missing'}",
    )


async def invoke(
    cap_id: str,
    payload: dict[str, Any],
    tenant: TenantContext,
    user: str | None = None,  # noqa: ARG001 — 预留与路由签名对齐
) -> AsyncIterator[dict[str, Any]]:
    """按 capability id 分发调用，产出事件字典（非 SSE 文本）。"""
    from backend.core.capability.governance import (
        check_cap_quota,
        check_cap_rate_limit,
        guard_output_text,
        prepare_payload_with_guards,
        record_cap_quota_usage,
    )

    registry = get_capability_registry()
    spec = registry.get(cap_id)  # CAP_001 / CAP_002

    _check_permission(spec, tenant)
    check_cap_rate_limit(tenant.tenant_id)
    check_cap_quota(tenant.tenant_id)

    safe_payload = await prepare_payload_with_guards(payload)
    collected: list[str] = []

    if spec.kind == CapabilityKind.MODEL:
        async for frame in _invoke_model(spec, safe_payload, tenant):
            if frame.get("event") == "token":
                collected.append(str(frame.get("data") or ""))
            if frame.get("event") != "done":
                yield frame
                continue
            # 出向护栏（整段）后 yield done
            full = "".join(collected)
            if full:
                await guard_output_text(full)
            # 日成本桶：model 路径用粗算（harness 已记 metrics；此处仅配额计数）
            usage_cost = 0.0
            try:
                from backend.core.cost_manager import calculate_cost, count_tokens

                usage_cost = float(
                    calculate_cost(spec.name, count_tokens(full)) if full else 0.0
                )
            except Exception:
                usage_cost = 0.0
            record_cap_quota_usage(tenant.tenant_id, calls=1, cost=usage_cost)
            yield frame
        return

    if spec.kind == CapabilityKind.EXTERNAL_APP:
        usage_cost = 0.0
        async for frame in _invoke_external_app(spec, safe_payload, tenant):
            if frame.get("event") == "token":
                collected.append(str(frame.get("data") or ""))
            if frame.get("event") == "usage":
                usage_cost = float((frame.get("data") or {}).get("cost") or 0)
            yield frame
        if collected:
            await guard_output_text("".join(collected))
        record_cap_quota_usage(tenant.tenant_id, calls=1, cost=usage_cost)
        return

    if spec.kind == CapabilityKind.AGENT:
        usage_cost = 0.0
        async for frame in _invoke_agent(spec, safe_payload, tenant):
            if frame.get("event") == "token":
                collected.append(str(frame.get("data") or ""))
            if frame.get("event") == "usage":
                usage_cost = float((frame.get("data") or {}).get("cost") or 0)
            yield frame
        if collected:
            await guard_output_text("".join(collected))
        record_cap_quota_usage(tenant.tenant_id, calls=1, cost=usage_cost)
        return

    if spec.kind == CapabilityKind.TOOL:
        usage_cost = 0.0
        async for frame in _invoke_tool(spec, safe_payload, tenant):
            if frame.get("event") == "token":
                collected.append(str(frame.get("data") or ""))
            if frame.get("event") == "usage":
                usage_cost = float((frame.get("data") or {}).get("cost") or 0)
            if frame.get("event") != "done":
                yield frame
                continue
            full = "".join(collected)
            if full:
                await guard_output_text(full)
            # model 子路径 harness 已记成本；rag 子路径若无 usage 则上面已累加
            if usage_cost <= 0 and collected:
                try:
                    from backend.core.cost_manager import calculate_cost, count_tokens

                    usage_cost = float(
                        calculate_cost(
                            str(spec.spec.get("model") or spec.name),
                            count_tokens(full),
                        )
                    )
                except Exception:
                    usage_cost = 0.0
            record_cap_quota_usage(tenant.tenant_id, calls=1, cost=usage_cost)
            yield frame
        return

    # workflow / datasource — 后续扩展（保持 CAP_001）
    raise CapabilityNotFoundError(
        message="unsupported_kind",
        detail=f"{cap_id}:{spec.kind.value}",
    )
