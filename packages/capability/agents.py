"""Hub ``kind=agent`` — 只编排子工具/MCP，不跑第二套聊天脑。

对话真源是 ``POST /chat/streaming``；多 agent 只走黑板 spawn subagent。
本模块按 ``spec.capabilities`` 展开 tool/model/rag，把子能力输出原样上抛。
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from packages.auth.models import TenantContext
from packages.auth.subagent import make_sub_agent_context
from packages.capability.errors import (
    CapabilityGovernanceRequiredError,
    CapabilityUpstreamError,
)
from packages.capability.models import CapabilityKind, CapabilitySpec

MAX_AGENT_DEPTH = 3


@dataclass
class AgentSpec:
    """从 kind=agent 的 CapabilitySpec 解析出的门面描述。"""

    id: str
    name: str
    role: str = ""
    system_prompt_ref: str = ""
    capabilities: list[str] = field(default_factory=list)
    memory: bool = True


def agent_spec_from_capability(spec: CapabilitySpec) -> AgentSpec:
    raw = dict(spec.spec or {})
    caps = raw.get("capabilities") or []
    if not isinstance(caps, list):
        caps = []
    return AgentSpec(
        id=spec.id,
        name=spec.name,
        role=str(raw.get("role") or ""),
        system_prompt_ref=str(raw.get("system_prompt_ref") or ""),
        capabilities=[str(c) for c in caps],
        memory=bool(raw.get("memory", True)),
    )


def validate_agent_spec(spec: CapabilitySpec) -> None:
    """注册时校验：自引用能力集拒绝。"""
    if spec.kind != CapabilityKind.AGENT:
        return
    agent = agent_spec_from_capability(spec)
    if spec.id in agent.capabilities:
        raise CapabilityGovernanceRequiredError(
            message="agent_self_reference",
            detail=f"{spec.id}:capabilities_include_self",
        )


def _message_from_payload(payload: dict[str, Any]) -> str:
    for key in ("message", "input", "query"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    msgs = payload.get("messages")
    if isinstance(msgs, list):
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "user":
                content = m.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
    return ""


def _audit_agent_invoke(
    *,
    capability_id: str,
    tenant: TenantContext,
    input_text: str,
    output_text: str = "",
    latency_ms: float = 0.0,
    cost: float = 0.0,
    error_code: str | None = None,
    trace_id: str = "",
) -> None:
    from packages.audit import write_audit_sync

    write_audit_sync(
        {
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id,
            "action": "agent.invoke",
            "trace_id": trace_id or str(uuid.uuid4()),
            "input_text": (input_text or "")[:2000],
            "output_text": (output_text or "")[:2000],
            "model": capability_id,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": cost,
            "latency_ms": latency_ms,
            "error_code": error_code,
            "ip_address": "",
            "user_agent": "",
            "created_at": datetime.utcnow(),
        }
    )


async def _stream_chunks(text: str, *, chunk_size: int = 8) -> AsyncIterator[str]:
    if not text:
        yield ""
        return
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]


def _leaf_stub_mode_enabled() -> bool:
    """``LEAF_STUB_MODE``（或旧名 ``CAPABILITY_AGENT_LEAF_STUB``）为真时启用演示 stub。"""
    flag = (
        os.getenv("LEAF_STUB_MODE") or os.getenv("CAPABILITY_AGENT_LEAF_STUB") or ""
    ).strip().lower()
    return flag in ("1", "true", "yes", "on")


def _is_leaf_stub(spec: CapabilitySpec) -> bool:
    """仅当 stub 模式开启且 ``spec.leaf=true`` 时走演示 stub（Task 30b）。

    默认走真实 ``invoke()``；``leaf`` 仅作降级标记，不再单独触发 stub。
    """
    if not _leaf_stub_mode_enabled():
        return False
    raw = spec.spec if isinstance(spec.spec, dict) else {}
    return raw.get("leaf") is True


def _should_chain_audit(spec: CapabilitySpec) -> bool:
    """``spec.chain_audit=false`` 时不写入 agent.invoke 主链审计（如 nexusai-chat）。"""
    raw = spec.spec if isinstance(spec.spec, dict) else {}
    return raw.get("chain_audit", True) is not False


async def _invoke_leaf_stub(
    cap_id: str,
    payload: dict[str, Any],
    tenant: TenantContext,
    *,
    trace_id: str,
    do_audit: bool,
) -> AsyncIterator[dict[str, Any]]:
    """叶子 stub：可选审计 + 短文本流（``spec.leaf`` 演示链）。"""
    t0 = time.perf_counter()
    message = _message_from_payload(payload)
    text = f"[{cap_id}] processed: {message[:120]}"
    if do_audit:
        _audit_agent_invoke(
            capability_id=cap_id,
            tenant=tenant,
            input_text=message,
            output_text=text,
            latency_ms=(time.perf_counter() - t0) * 1000,
            cost=0.001,
            trace_id=trace_id,
        )
    async for part in _stream_chunks(text):
        if part:
            yield {"event": "token", "data": part, "cost_source": "invoke"}
    yield {
        "event": "usage",
        "data": {"cost": 0.001, "tokens": max(1, len(text) // 4), "upstream": cap_id},
        "cost_source": "invoke",
    }


async def _invoke_child_capability(
    child: CapabilitySpec,
    payload: dict[str, Any],
    tenant: TenantContext,
    *,
    trace_id: str,
    parent_agent_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """非 agent 子能力：leaf stub 或真实 ``invoke()``。"""
    child_tenant = tenant
    if parent_agent_id:
        child_tenant = make_sub_agent_context(
            tenant,
            agent_id=parent_agent_id,
            parent_trace_id=trace_id,
        )
    if _is_leaf_stub(child):
        async for frame in _invoke_leaf_stub(
            child.id,
            payload,
            child_tenant,
            trace_id=trace_id,
            do_audit=_should_chain_audit(child),
        ):
            yield frame
        return

    # 真实分发（model / tool / MCP）；external_app 会在 invoke 被封死
    from packages.capability.invoke import invoke

    if _should_chain_audit(child):
        _audit_agent_invoke(
            capability_id=child.id,
            tenant=child_tenant,
            input_text=_message_from_payload(payload),
            trace_id=trace_id,
        )
    async for frame in invoke(child.id, payload, child_tenant):
        yield frame


async def invoke_agent(
    spec: CapabilitySpec,
    payload: dict[str, Any],
    tenant: TenantContext,
    *,
    _depth: int = 0,
    _chain: list[str] | None = None,
    _trace_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """展开子能力链。禁止调用 AgentService / 禁止再造一份聊天回复。"""
    if spec.kind != CapabilityKind.AGENT:
        raise CapabilityUpstreamError(
            message="not_an_agent",
            detail=spec.id,
        )
    if _depth >= MAX_AGENT_DEPTH:
        raise CapabilityUpstreamError(
            message="agent_depth_exceeded",
            detail=f"{spec.id}:max={MAX_AGENT_DEPTH}",
        )

    # Wave 8 拍板 8A: Hub agent stack counts toward composition budget
    try:
        from packages.workflow.composition import (
            CompositionDepthExceeded,
            check_composition_budget,
        )

        run_depth = int(payload.get("_composition_run_depth") or 0)
        check_composition_budget(run_depth, agent_stack=_depth + 1)
    except CompositionDepthExceeded as exc:
        raise CapabilityUpstreamError(
            message="DEPTH_EXCEEDED",
            detail=str(exc),
        ) from exc

    from packages.capability.invoke import _check_permission

    _check_permission(spec, tenant)
    validate_agent_spec(spec)
    agent = agent_spec_from_capability(spec)
    message = _message_from_payload(payload)
    if not message:
        raise CapabilityUpstreamError(message="empty_message", detail=spec.id)

    trace_id = _trace_id or str(uuid.uuid4())
    # 可变共享链：父子与叶子追加同一列表，顶层 done 一次吐出
    chain = _chain if _chain is not None else []
    if spec.id in chain:
        raise CapabilityUpstreamError(
            message="agent_cycle_detected",
            detail="→".join([*chain, spec.id]),
        )
    chain.append(spec.id)

    t0 = time.perf_counter()
    _audit_agent_invoke(
        capability_id=spec.id,
        tenant=tenant,
        input_text=message,
        trace_id=trace_id,
    )

    from packages.capability.registry import get_capability_registry

    registry = get_capability_registry()
    child_tenant = (
        make_sub_agent_context(tenant, agent_id=spec.id, parent_trace_id=trace_id)
        if _depth == 0
        else tenant
    )

    for cap_id in agent.capabilities:
        child = registry.get(cap_id)
        if child.kind == CapabilityKind.AGENT:
            async for frame in invoke_agent(
                child,
                payload,
                child_tenant,
                _depth=_depth + 1,
                _chain=chain,
                _trace_id=trace_id,
            ):
                if frame.get("event") == "done":
                    continue
                yield frame
        else:
            if _should_chain_audit(child) and child.id not in chain:
                chain.append(child.id)
            async for frame in _invoke_child_capability(
                child,
                payload,
                child_tenant,
                trace_id=trace_id,
                parent_agent_id=spec.id if _depth == 0 else None,
            ):
                if frame.get("event") != "done":
                    yield frame

    latency = (time.perf_counter() - t0) * 1000
    yield {
        "event": "done",
        "data": {
            "capability_id": spec.id,
            "call_chain": chain,
            "nested_capabilities": list(agent.capabilities),
            "latency_ms": latency,
            "upstream": spec.id,
        },
        "cost_source": "invoke",
    }


class AgentRuntime:
    """薄封装，便于测试与扩展。"""

    @staticmethod
    async def invoke(
        agent_id: str,
        payload: dict[str, Any],
        tenant: TenantContext,
    ) -> AsyncIterator[dict[str, Any]]:
        from packages.capability.registry import get_capability_registry

        spec = get_capability_registry().get(agent_id)
        async for frame in invoke_agent(spec, payload, tenant):
            yield frame
