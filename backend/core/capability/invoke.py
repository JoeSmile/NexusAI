"""Capability invoke 核心分发（Task 30.04）。

分层约束: 本模块禁止 import ``backend.pipeline``。
SSE 组帧 / LangFuse 根注入在 routers 层（30.06）。

成本幂等: kind=model 由 harness 内部 ``record_consumption``;
external_app / agent 由本层记账并带 ``cost_source: invoke``。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from backend.core.auth.models import TenantContext
from backend.core.capability.errors import (
    CapabilityGovernanceRequiredError,
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
        raise CapabilityGovernanceRequiredError(
            message="invalid_payload",
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
    """占位：Agent 门面在 30.24。"""
    try:
        from backend.core.capability import agents as agent_runtime  # type: ignore[attr-defined]
    except ImportError:
        agent_runtime = None

    if agent_runtime is None or not hasattr(agent_runtime, "invoke_agent"):
        raise CapabilityUpstreamError(
            message="agent_runtime_not_ready",
            detail="await_30.24",
        )

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


async def invoke(
    cap_id: str,
    payload: dict[str, Any],
    tenant: TenantContext,
    user: str | None = None,  # noqa: ARG001 — 预留与路由签名对齐
) -> AsyncIterator[dict[str, Any]]:
    """按 capability id 分发调用，产出事件字典（非 SSE 文本）。"""
    registry = get_capability_registry()
    spec = registry.get(cap_id)  # CAP_001 / CAP_002

    _check_permission(spec, tenant)

    if spec.kind == CapabilityKind.MODEL:
        async for frame in _invoke_model(spec, payload, tenant):
            yield frame
        return

    if spec.kind == CapabilityKind.EXTERNAL_APP:
        async for frame in _invoke_external_app(spec, payload, tenant):
            yield frame
        return

    if spec.kind == CapabilityKind.AGENT:
        async for frame in _invoke_agent(spec, payload, tenant):
            yield frame
        return

    # tool / workflow / datasource — 后续扩展
    raise CapabilityNotFoundError(
        message="unsupported_kind",
        detail=f"{cap_id}:{spec.kind.value}",
    )
