"""Agent 门面 — 包装 AgentService，支持嵌套能力链（Task 30.24）。

真实 Runtime 在 ``backend/agent/``（经 ``routers/agent.py`` 挂载）。
``backend.modules.agent`` 仅保留 ``protocol``（MCP）；Task 31 已删除孤儿实现树。

深度 0 双路径（拍板 C，保留）:
- **嵌套链**: 按 ``capabilities`` 顺序展开子能力（审计/流式 call_chain）。
- **回复正文**: 以 ``AgentService.process_message`` 为准；仅当其失败/空时
  回退到嵌套链 token 拼接。嵌套链成本/审计仍记账，不代表最终回复源。
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.core.auth.models import TenantContext
from backend.core.capability.errors import (
    CapabilityGovernanceRequiredError,
    CapabilityUpstreamError,
)
from backend.core.capability.models import CapabilityKind, CapabilitySpec

logger = logging.getLogger(__name__)

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
    from backend.core.audit import write_audit_sync

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
    """``spec.chain_audit=false`` 时不写入 agent.invoke 主链审计（如 contextgate-chat）。"""
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
) -> AsyncIterator[dict[str, Any]]:
    """非 agent 子能力：leaf stub 或真实 ``invoke()``。"""
    if _is_leaf_stub(child):
        async for frame in _invoke_leaf_stub(
            child.id,
            payload,
            tenant,
            trace_id=trace_id,
            do_audit=_should_chain_audit(child),
        ):
            yield frame
        return

    # 真实分发（model / external_app 等）；避免再包一层 agent 审计双计
    from backend.core.capability.invoke import invoke

    if _should_chain_audit(child):
        _audit_agent_invoke(
            capability_id=child.id,
            tenant=tenant,
            input_text=_message_from_payload(payload),
            trace_id=trace_id,
        )
    async for frame in invoke(child.id, payload, tenant):
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
    """门面入口：嵌套能力链 + AgentService.process_message + 分片流式。

    深度 0: AgentService 拥有最终 reply；嵌套链负责可见 call_chain / 审计，
    仅在 AgentService 无有效回复时回退嵌套文本（见模块 docstring）。
    """
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

    from backend.core.capability.invoke import _check_permission

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

    from backend.core.capability.registry import get_capability_registry

    registry = get_capability_registry()
    nested_text_parts: list[str] = []

    # 主链：按 capabilities 顺序展开；agent 递归，叶子走 _invoke_leaf
    for cap_id in agent.capabilities:
        child = registry.get(cap_id)
        if child.kind == CapabilityKind.AGENT:
            async for frame in invoke_agent(
                child,
                payload,
                tenant,
                _depth=_depth + 1,
                _chain=chain,
                _trace_id=trace_id,
            ):
                if frame.get("event") == "token":
                    nested_text_parts.append(str(frame.get("data") or ""))
                if frame.get("event") == "done":
                    continue
                yield frame
        else:
            if _should_chain_audit(child) and child.id not in chain:
                chain.append(child.id)
            async for frame in _invoke_child_capability(
                child, payload, tenant, trace_id=trace_id
            ):
                if frame.get("event") == "token":
                    nested_text_parts.append(str(frame.get("data") or ""))
                if frame.get("event") != "done":
                    yield frame

    # 顶层：AgentService 拥有 reply；嵌套链已跑完（审计/call_chain）
    reply = ""
    if _depth == 0:
        try:
            from backend.services.agent_service import get_agent_service

            svc = get_agent_service()
            result = await svc.process_message(
                user_id=tenant.user_id,
                message=message,
                conversation_id=str(payload.get("conversation_id") or "") or None,
                capabilities=list(agent.capabilities),
                tenant_id=tenant.tenant_id,
            )
            if result.get("success"):
                data = result.get("data") or {}
                reply = str(
                    data.get("response")
                    or data.get("output")
                    or data.get("message")
                    or ""
                )
            else:
                reply = str(result.get("error") or "")
        except Exception as exc:
            logger.info("AgentService fallback for %s: %s", spec.id, exc)
            reply = ""

    if not reply:
        nested = "".join(nested_text_parts).strip()
        reply = nested or f"[{spec.id}] ok"

    if _depth == 0:
        async for part in _stream_chunks(reply):
            if part:
                yield {"event": "token", "data": part, "cost_source": "invoke"}

    latency = (time.perf_counter() - t0) * 1000
    cost = 0.01 * (1 + _depth)
    if _depth == 0:
        yield {
            "event": "usage",
            "data": {
                "cost": cost,
                "tokens": max(1, len(reply) // 4),
                "upstream": spec.id,
            },
            "cost_source": "invoke",
        }
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
        from backend.core.capability.registry import get_capability_registry

        spec = get_capability_registry().get(agent_id)
        async for frame in invoke_agent(spec, payload, tenant):
            yield frame
