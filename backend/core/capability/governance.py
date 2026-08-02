"""Capability 治理强制（Task 30.05）— 护栏 / 分钟桶限流 / 日配额。

不依赖 LangGraph 节点；供 invoke 与 registry 复用。
限流用 Redis INCR+EXPIRE 分钟桶（对齐 Task 29 ``rl:rag:*``），不用内存 TokenBucket。
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from backend.core.capability.errors import (
    CapabilityGovernanceRequiredError,
    CapabilityQuotaExceededError,
)
from backend.core.capability.models import CapabilityKind, CapabilitySpec
from backend.core.errors import ContextGateException, ErrorCode
from backend.core.guardrails.input_guard import check_input
from backend.core.guardrails.output_guard import check_output

logger = logging.getLogger(__name__)

# 分钟桶默认（可用 env 覆盖）
_CAP_RATE_LIMIT_PER_MIN = int(os.getenv("CAP_RATE_LIMIT_PER_MIN", "60") or 60)


def _redis():
    """优先复用 RAG cache 的 redis 客户端。"""
    try:
        from backend.modules.rag.cache import get_redis

        return get_redis()
    except Exception as exc:
        logger.debug("cap governance redis unavailable: %s", exc)
        return None


def _minute_bucket() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M")


def _day_bucket() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def validate_governance_declaration(spec: CapabilitySpec) -> None:
    """非 model 必须显式声明 ``spec.governance``，否则 CAP_004。"""
    if spec.kind == CapabilityKind.MODEL:
        return
    gov = spec.spec.get("governance") if isinstance(spec.spec, dict) else None
    if gov is None or gov is False:
        raise CapabilityGovernanceRequiredError(
            message="governance_required",
            detail=f"{spec.id}:declare_governance_in_spec",
        )


async def guard_input_text(message: str) -> str:
    """入向护栏；blocked → GUARD_001 / CAP_004 语义。"""
    result = await check_input(message)
    if result.action == "blocked":
        raise ContextGateException(
            ErrorCode.PROMPT_INJECTION.value,
            "prompt_injection",
            detail=result.reason or "blocked",
        )
    return result.redacted_text or message


async def guard_output_text(text: str) -> str:
    """出向护栏；blocked → GUARD_003。"""
    result = await check_output(text)
    if result.action == "blocked":
        raise ContextGateException(
            ErrorCode.OUTPUT_BLOCKED.value,
            "output_blocked",
            detail=result.reason or "blocked",
        )
    return result.redacted_text or text


def check_cap_rate_limit(tenant_id: str) -> None:
    """Redis 分钟桶 ``rl:cap:req:{tenant}:{YYYYMMDDHHMM}``；超限 RATE_001。"""
    r = _redis()
    if r is None:
        return
    tid = tenant_id or "default"
    limit = int(os.getenv("CAP_RATE_LIMIT_PER_MIN", str(_CAP_RATE_LIMIT_PER_MIN)) or 60)
    key = f"rl:cap:req:{tid}:{_minute_bucket()}"
    try:
        n = int(r.incr(key))
        if n == 1:
            r.expire(key, 70)
        if n > limit:
            raise ContextGateException(
                ErrorCode.RATE_LIMITED.value,
                "rate_limited",
                detail=f"cap_req>{limit}/min",
            )
    except ContextGateException:
        raise
    except Exception as exc:
        logger.debug("cap rate limit skipped: %s", exc)


def check_cap_quota(tenant_id: str, *, estimated_cost: float = 0.0) -> None:
    """日调用次数 / 日成本上限（30.03 env）；超限 CAP_005。

    只读检查；真正计数在 ``record_cap_quota_usage``。
    """
    from backend.core.capability.registry import (
        get_cap_quota_daily_calls,
        get_cap_quota_daily_cost_usd,
    )

    r = _redis()
    if r is None:
        return
    tid = tenant_id or "default"
    day = _day_bucket()
    calls_key = f"rl:cap:calls:{tid}:{day}"
    cost_key = f"rl:cap:cost:{tid}:{day}"
    try:
        calls = int(r.get(calls_key) or 0)
        cost = float(r.get(cost_key) or 0)
        max_calls = get_cap_quota_daily_calls()
        max_cost = get_cap_quota_daily_cost_usd()
        if calls >= max_calls:
            raise CapabilityQuotaExceededError(
                detail=f"calls>={max_calls}/day",
            )
        if cost + float(estimated_cost or 0) > max_cost:
            raise CapabilityQuotaExceededError(
                detail=f"cost>{max_cost}/day",
            )
    except CapabilityQuotaExceededError:
        raise
    except Exception as exc:
        logger.debug("cap quota check skipped: %s", exc)


def record_cap_quota_usage(
    tenant_id: str,
    *,
    cost: float = 0.0,
    calls: int = 1,
) -> None:
    """invoke 成功路径记账（日桶）。"""
    r = _redis()
    if r is None:
        return
    tid = tenant_id or "default"
    day = _day_bucket()
    calls_key = f"rl:cap:calls:{tid}:{day}"
    cost_key = f"rl:cap:cost:{tid}:{day}"
    try:
        pipe = r.pipeline()
        if calls:
            pipe.incrby(calls_key, int(calls))
            pipe.expire(calls_key, 90000)  # ~25h
        if cost:
            pipe.incrbyfloat(cost_key, float(cost))
            pipe.expire(cost_key, 90000)
        pipe.execute()
    except Exception as exc:
        logger.debug("cap quota record skipped: %s", exc)


async def prepare_payload_with_guards(payload: dict[str, Any]) -> dict[str, Any]:
    """对 payload 中的用户文本做入向护栏，返回副本。"""
    out = dict(payload)
    msgs = out.get("messages")
    if isinstance(msgs, list) and msgs:
        new_msgs = []
        for m in msgs:
            if isinstance(m, dict) and m.get("role") == "user" and m.get("content"):
                redacted = await guard_input_text(str(m["content"]))
                new_msgs.append({**m, "content": redacted})
            else:
                new_msgs.append(m)
        out["messages"] = new_msgs
        return out
    for key in ("message", "input", "query"):
        if out.get(key):
            out[key] = await guard_input_text(str(out[key]))
            break
    return out
