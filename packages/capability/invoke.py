"""Capability invoke 核心分发（Task 30.04 / 30b）。

分层约束: 本模块禁止 import ``packages.pipeline``。
SSE 组帧 / LangFuse 根注入在 routers 层（30.06）。

成本幂等: kind=model 由 harness 内部 ``record_consumption``;
external_app / agent 由本层记账并带 ``cost_source: invoke``。
kind=tool 经 ``spec.executor`` 映射到 model / rag（Task 30b）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from backend.core.errors import ErrorCode, NexusAIException
from packages.auth.models import TenantContext
from packages.capability.errors import (
    CapabilityNotFoundError,
    CapabilityUpstreamError,
)
from packages.capability.models import CapabilityKind, CapabilityProvider, CapabilitySpec
from packages.capability.registry import (
    get_capability_registry,
    resolve_credential,
)

logger = logging.getLogger(__name__)

# tool 叶子 executor → 真实执行器（不按 capability id 硬编码）
_TOOL_EXECUTOR_MODEL = frozenset({"model", "chat", "llm"})
_TOOL_EXECUTOR_RAG = frozenset({"rag", "rag_ask", "rag-ask"})
_TOOL_EXECUTOR_CONTENT_OPS = frozenset({"content_ops", "content-ops", "contentops"})
_TOOL_EXECUTOR_BUILTIN = frozenset({"builtin"})


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


def capability_visible_to(spec: CapabilitySpec, tenant: TenantContext) -> bool:
    """租户可见性：与 list 过滤一致（* / 空 / 本租户；跨租户角色放行）。"""
    if spec.tenant_id not in ("*", "", tenant.tenant_id):
        if not tenant.is_cross_tenant:
            return False
    nested = spec.spec if isinstance(spec.spec, dict) else {}
    allowlist = nested.get("tenant_allowlist")
    if isinstance(allowlist, list) and allowlist:
        allowed = {str(t).strip() for t in allowlist if str(t).strip()}
        if allowed and tenant.tenant_id not in allowed and not tenant.is_cross_tenant:
            return False
    needed = (spec.permission or "").strip() or "chat:write"
    return tenant.has_permission(needed)


def _check_permission(spec: CapabilitySpec, tenant: TenantContext) -> None:
    """invoke / preflight 闸门。

    跨租户 private → CAP_001（与 list 隐藏对齐，避免探测存在性）。
    本租户可见但缺 permission → AUTH_002（与既有鉴权语义一致）。
    """
    if spec.tenant_id not in ("*", "", tenant.tenant_id) and not tenant.is_cross_tenant:
        raise CapabilityNotFoundError(
            message="capability_not_found",
            detail=spec.id,
        )
    needed = (spec.permission or "").strip() or "chat:write"
    if not tenant.has_permission(needed):
        # Wave E: workflow_grant 命中（caps 不并进 extra_permissions）
        from packages.workflow.grants import current_grant_covers_capability

        if not current_grant_covers_capability():
            raise NexusAIException(
                ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS.value,
                "insufficient_permissions",
                detail=needed,
            )


async def _invoke_model(
    spec: CapabilitySpec,
    payload: dict[str, Any],
    tenant: TenantContext,
) -> AsyncIterator[dict[str, Any]]:
    from packages.harness import LLMHarness

    messages = _messages_from_payload(payload)
    if not messages:
        raise NexusAIException(
            ErrorCode.REQ_INVALID.value,
            "invalid_payload",
            detail="messages_or_message_required",
        )

    model_name = str(spec.spec.get("model") or spec.name)
    retry_attempt = int(payload.get("_orchestrator_retry_attempt") or 1)
    override = payload.get("_model_override")
    if override:
        model_name = str(override)
    elif retry_attempt > 1:
        from backend.core.model_registry import resolve_model_for_retry

        model_name, _ = resolve_model_for_retry(model_name, retry_attempt)
    api_key_ref = str(spec.spec.get("api_key_ref") or "")
    api_key = resolve_credential(api_key_ref, tenant_id=tenant.tenant_id) or None
    base_url = str(spec.spec.get("base_url") or "") or None
    if base_url:
        from packages.security.url_guard import UrlValidationError, validate_base_url

        try:
            base_url = validate_base_url(base_url)
        except UrlValidationError as exc:
            raise NexusAIException(
                ErrorCode.REQ_INVALID.value,
                exc.code,
                detail="invalid_base_url",
            ) from exc
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
        from packages.capability import connectors  # type: ignore[attr-defined]
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
    """Agent 门面分发（``packages.capability.agents``）。"""
    from packages.capability import agents as agent_runtime

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
        raise NexusAIException(
            ErrorCode.REQ_INVALID.value,
            "invalid_payload",
            detail="messages_or_message_required",
        )
    question = messages[-1]["content"]
    search_k = int(payload.get("search_k") or spec.spec.get("search_k") or 3)

    try:
        result = await asyncio.to_thread(
            get_rag_service().ask,
            question,
            search_k,
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id or "anonymous",
        )
    except NexusAIException:
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
            # Wave D evidence：透传 sources（不改变 token/usage 语义）
            "sources": list((result or {}).get("sources") or []),
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
    if executor in _TOOL_EXECUTOR_CONTENT_OPS:
        from packages.content_ops.invoke_exec import invoke_content_ops

        async for frame in invoke_content_ops(spec, payload, tenant):
            yield frame
        return
    if executor in _TOOL_EXECUTOR_BUILTIN:
        from packages.capability.builtin.handlers import (
            builtin_result_to_json,
            invoke_builtin_handler,
        )

        handler_id = str((spec.spec or {}).get("builtin_handler") or spec.id)
        result = await invoke_builtin_handler(
            handler_id,
            payload,
            tenant,
            spec_body=spec.spec,
        )
        text = builtin_result_to_json(result)
        chunk = 48
        for i in range(0, max(len(text), 1), chunk):
            part = text[i : i + chunk] if text else ""
            if part:
                yield {"event": "token", "data": part, "cost_source": "invoke"}
        yield {
            "event": "done",
            "data": {
                "capability_id": spec.id,
                "kind": spec.kind.value,
                "executor": "builtin",
                "result": result,
            },
            "cost_source": "invoke",
        }
        return
    if executor == "mcp" or spec.provider == CapabilityProvider.MCP:
        from packages.capability.connectors.mcp_server import invoke_mcp

        async for frame in invoke_mcp(spec, payload, tenant):
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
    from packages.capability.governance import (
        guard_output_text,
        prepare_payload_with_guards,
        record_cap_quota_usage,
    )
    from packages.capability.governance_chain import run_governance_chain

    registry = get_capability_registry()
    spec = registry.get(cap_id)  # CAP_001 / CAP_002

    # Task 56: 叙事治理链（policy→budget→approval→IAM→audit explain）
    explain = run_governance_chain(
        spec,
        tenant,
        payload if isinstance(payload, dict) else {},
        check_permission=_check_permission,
    )
    from backend.core.audit import write_governance_audit
    from backend.core.audit_context import bind_audit_lineage, get_audit_lineage
    from backend.observability.langfuse_client import current_langfuse_trace_ids

    lineage = get_audit_lineage()
    tool_use_id = lineage.tool_use_id or (
        f"{cap_id}:{explain.idempotency_key or 'invoke'}"
    )
    bind_audit_lineage(
        trace_id=lineage.trace_id or tool_use_id,
        parent_trace_id=lineage.parent_trace_id or lineage.trace_id,
        tool_use_id=tool_use_id,
    )
    write_governance_audit(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        capability_id=cap_id,
        explain=explain.to_dict(),
        lineage=get_audit_lineage(),
        langfuse_ids=current_langfuse_trace_ids(),
        agent_role=tenant.agent_role,
        parent_agent_id=tenant.parent_agent_id,
    )

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
