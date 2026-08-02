"""Dify / Coze 外部应用连接器（Task 30.07）。

统一产出 invoke 事件帧:
  ``{"event":"token"|"usage"|"done"|"error", "data":..., "cost_source":"invoke"}``

Mock: ``CAPABILITY_UPSTREAM_MOCK=true`` 或 ``LLM_PROVIDER=mock`` 时不打真实上游,
仍走请求构造 + SSE 解析路径(用内置 fixture 字节流)。
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from backend.core.auth.models import TenantContext
from backend.core.capability.errors import CapabilityUpstreamError
from backend.core.capability.models import CapabilityProvider, CapabilitySpec
from backend.core.capability.registry import resolve_credential
from backend.core.circuit_breaker import CircuitBreaker, CircuitState

logger = logging.getLogger(__name__)

_BREAKERS: dict[str, CircuitBreaker] = {}


def _breaker(name: str) -> CircuitBreaker:
    if name not in _BREAKERS:
        _BREAKERS[name] = CircuitBreaker(
            failure_threshold=5, recovery_timeout=30.0, name=name
        )
    return _BREAKERS[name]


def _mock_enabled() -> bool:
    if os.getenv("CAPABILITY_UPSTREAM_MOCK", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    return os.getenv("LLM_PROVIDER", "").strip().lower() == "mock"


@dataclass(frozen=True)
class UpstreamRequest:
    """可单测断言的上游请求描述。"""

    method: str
    url: str
    headers: dict[str, str]
    json_body: dict[str, Any]
    timeout: float
    provider: str


def _user_id(tenant: TenantContext, payload: dict[str, Any]) -> str:
    return str(payload.get("user") or payload.get("user_id") or tenant.user_id or "user")


def _inputs(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("inputs"), dict):
        return dict(payload["inputs"])
    text = payload.get("message") or payload.get("input") or payload.get("query") or ""
    if text:
        return {"query": str(text), "input": str(text)}
    return {}


def _timeout(spec: CapabilitySpec) -> float:
    raw = spec.spec.get("timeout_s") or spec.spec.get("timeout") or 60
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 60.0


def _api_key(spec: CapabilitySpec, tenant: TenantContext) -> str:
    ref = str(spec.spec.get("api_key_ref") or "")
    key = resolve_credential(ref, tenant_id=tenant.tenant_id)
    if not key:
        # 允许 spec 内联测试 key（勿用于生产）
        key = str(spec.spec.get("api_key") or "")
    if not key and not _mock_enabled():
        raise CapabilityUpstreamError(
            message="missing_credential",
            detail=ref or spec.id,
        )
    return key or "mock-key"


def build_dify_request(
    spec: CapabilitySpec, payload: dict[str, Any], tenant: TenantContext
) -> UpstreamRequest:
    base = str(spec.spec.get("base_url") or "").rstrip("/")
    if not base:
        raise CapabilityUpstreamError(message="missing_base_url", detail=spec.id)
    # base 可含 /v1；默认打 workflows/run
    path = str(spec.spec.get("path") or "/workflows/run")
    if not path.startswith("/"):
        path = "/" + path
    url = base + path
    key = _api_key(spec, tenant)
    body: dict[str, Any] = {
        "inputs": _inputs(payload),
        "response_mode": "streaming",
        "user": _user_id(tenant, payload),
    }
    wf = spec.spec.get("workflow_id") or payload.get("workflow_id")
    if wf:
        body["workflow_id"] = str(wf)
    return UpstreamRequest(
        method="POST",
        url=url,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        json_body=body,
        timeout=_timeout(spec),
        provider=CapabilityProvider.DIFY.value,
    )


def build_coze_request(
    spec: CapabilitySpec, payload: dict[str, Any], tenant: TenantContext
) -> UpstreamRequest:
    base = str(spec.spec.get("base_url") or "https://api.coze.com").rstrip("/")
    path = str(spec.spec.get("path") or "/v3/chat")
    if not path.startswith("/"):
        path = "/" + path
    url = base + path
    key = _api_key(spec, tenant)
    bot_id = str(
        spec.spec.get("bot_id") or payload.get("bot_id") or spec.spec.get("app_id") or ""
    )
    text = (
        payload.get("message")
        or payload.get("input")
        or payload.get("query")
        or ""
    )
    body: dict[str, Any] = {
        "bot_id": bot_id,
        "user_id": _user_id(tenant, payload),
        "stream": True,
        "additional_messages": [
            {"role": "user", "content": str(text), "content_type": "text"}
        ],
    }
    return UpstreamRequest(
        method="POST",
        url=url,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        json_body=body,
        timeout=_timeout(spec),
        provider=CapabilityProvider.COZE.value,
    )


def build_upstream_request(
    spec: CapabilitySpec, payload: dict[str, Any], tenant: TenantContext
) -> UpstreamRequest:
    if spec.provider == CapabilityProvider.DIFY:
        return build_dify_request(spec, payload, tenant)
    if spec.provider == CapabilityProvider.COZE:
        return build_coze_request(spec, payload, tenant)
    raise CapabilityUpstreamError(
        message="unsupported_provider",
        detail=spec.provider.value,
    )


def _estimate_cost(spec: CapabilitySpec, text: str) -> tuple[float, int]:
    try:
        from backend.core.cost_manager import calculate_cost, count_tokens

        tokens = count_tokens(text) if text else 0
        per_1k = float((spec.cost_model or {}).get("cost_per_1k") or 0.0)
        if per_1k > 0 and tokens:
            return per_1k * tokens / 1000.0, tokens
        # 回退: 用 calculate_cost(model=spec.id) 的 default 表
        return float(calculate_cost(spec.id, tokens)), tokens
    except Exception:
        return 0.0, 0


def parse_upstream_sse_line(
    line: str, *, provider: str
) -> list[dict[str, Any]]:
    """把上游 SSE 行转为 0..n 个统一事件帧(不含 cost_source)。"""
    raw = line.strip()
    if not raw or raw.startswith(":"):
        return []
    if raw.startswith("data:"):
        raw = raw[5:].strip()
    if raw in ("[DONE]", "DONE"):
        return []
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # 纯文本 chunk
        if raw:
            return [{"event": "token", "data": raw}]
        return []

    if not isinstance(obj, dict):
        return []

    frames: list[dict[str, Any]] = []
    raw_data = obj.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    if provider == CapabilityProvider.DIFY.value:
        ev = str(obj.get("event") or "")
        if ev in ("text_chunk", "agent_message", "message"):
            text = (
                data.get("text")
                or data.get("answer")
                or obj.get("answer")
                or obj.get("text")
                or ""
            )
            if text:
                frames.append({"event": "token", "data": str(text)})
        elif ev in ("workflow_finished", "message_end", "tts_message_end"):
            pass
        elif ev == "error":
            frames.append(
                {
                    "event": "error",
                    "data": {
                        "code": "CAP_003",
                        "message": str(
                            data.get("message") or obj.get("message") or "upstream"
                        ),
                    },
                }
            )
        else:
            # blocking 风格整包
            answer = obj.get("answer") or data.get("answer") or data.get("text")
            if answer:
                frames.append({"event": "token", "data": str(answer)})
    elif provider == CapabilityProvider.COZE.value:
        ev = str(obj.get("event") or obj.get("type") or "")
        if ev in ("conversation.message.delta", "message", "answer"):
            content = obj.get("content") or data.get("content") or ""
            if content:
                frames.append({"event": "token", "data": str(content)})
        elif "content" in obj and obj.get("role") == "assistant":
            frames.append({"event": "token", "data": str(obj["content"])})
        elif ev in ("error", "conversation.chat.failed"):
            frames.append(
                {
                    "event": "error",
                    "data": {
                        "code": "CAP_003",
                        "message": str(obj.get("msg") or obj.get("message") or "upstream"),
                    },
                }
            )
    else:
        token = obj.get("token") or obj.get("text") or obj.get("answer")
        if token:
            frames.append({"event": "token", "data": str(token)})
    return frames


def _fixture_sse(provider: str) -> str:
    if provider == CapabilityProvider.COZE.value:
        return (
            'data: {"event":"conversation.message.delta","content":"hello "}\n\n'
            'data: {"event":"conversation.message.delta","content":"coze"}\n\n'
            "data: [DONE]\n\n"
        )
    return (
        'data: {"event":"text_chunk","data":{"text":"hello "}}\n\n'
        'data: {"event":"text_chunk","data":{"text":"dify"}}\n\n'
        'data: {"event":"workflow_finished","data":{}}\n\n'
    )


async def _iter_sse_bytes(lines: AsyncIterator[str], provider: str) -> AsyncIterator[dict[str, Any]]:
    async for line in lines:
        for frame in parse_upstream_sse_line(line, provider=provider):
            yield frame


async def _mock_line_iter(provider: str) -> AsyncIterator[str]:
    for line in _fixture_sse(provider).splitlines():
        yield line


async def _http_line_iter(req: UpstreamRequest) -> AsyncIterator[str]:
    timeout = httpx.Timeout(req.timeout, connect=min(10.0, req.timeout))
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            req.method,
            req.url,
            headers=req.headers,
            json=req.json_body,
        ) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread())[:500]
                raise CapabilityUpstreamError(
                    message="upstream_http_error",
                    detail=f"{resp.status_code}:{body!r}",
                )
            async for line in resp.aiter_lines():
                yield line


async def invoke_external(
    spec: CapabilitySpec,
    payload: dict[str, Any],
    tenant: TenantContext,
) -> AsyncIterator[dict[str, Any]]:
    """连接器入口 — 供 ``capability.invoke`` 调用。"""
    req = build_upstream_request(spec, payload, tenant)
    breaker = _breaker(f"cap:{req.provider}:{spec.id}")
    if breaker.state == CircuitState.OPEN:
        raise CapabilityUpstreamError(
            message="circuit_open",
            detail=breaker.name,
        )

    collected: list[str] = []
    saw_error = False
    try:
        if _mock_enabled():
            line_iter = _mock_line_iter(req.provider)
        else:
            line_iter = _http_line_iter(req)

        async for frame in _iter_sse_bytes(line_iter, req.provider):
            if frame.get("event") == "token":
                collected.append(str(frame.get("data") or ""))
            if frame.get("event") == "error":
                saw_error = True
            yield {**frame, "cost_source": "invoke"}

        if saw_error:
            breaker._on_failure()
        else:
            breaker._on_success()
    except CapabilityUpstreamError:
        breaker._on_failure()
        raise
    except httpx.TimeoutException as e:
        breaker._on_failure()
        raise CapabilityUpstreamError(
            message="upstream_timeout",
            detail=str(e),
        ) from e
    except httpx.HTTPError as e:
        breaker._on_failure()
        raise CapabilityUpstreamError(
            message="upstream_http_error",
            detail=str(e),
        ) from e
    except Exception as e:
        breaker._on_failure()
        raise CapabilityUpstreamError(
            message="upstream_error",
            detail=str(e),
        ) from e

    text = "".join(collected)
    cost, tokens = _estimate_cost(spec, text)
    yield {
        "event": "usage",
        "data": {
            "cost": cost,
            "tokens": tokens,
            "upstream": req.provider,
        },
        "cost_source": "invoke",
    }
    yield {
        "event": "done",
        "data": {
            "capability_id": spec.id,
            "kind": spec.kind.value,
            "upstream": req.provider,
        },
        "cost_source": "invoke",
    }


__all__ = [
    "UpstreamRequest",
    "build_coze_request",
    "build_dify_request",
    "build_upstream_request",
    "invoke_external",
    "parse_upstream_sse_line",
]
