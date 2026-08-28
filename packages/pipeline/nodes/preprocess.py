"""Early preprocess — normalize + cheap GATE (Task 39)."""

from __future__ import annotations

import logging
import os

from backend.core.guardrails.deny_list import deny_list_hit
from backend.core.metrics import guardrails_blocked
from backend.core.rate_limiter import check_rate_limit
from backend.core.text_normalize import make_normalized_query_hash, normalize_text
from backend.observability.decorators import observe
from packages.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

_GATE_RESPONSE = "输入内容不符合安全规范，已被拦截。"

# 触发型消息启发式（GAP-2 / 40.86）：动态内容勿进 exact cache
_TRIGGER_ACTION = ("热点", "稿", "生成", "写一篇", "写一篇稿", "口播")
_TRIGGER_DOMAIN = ("教育", "内容", "选题", "分镜", "案例", "主播")


def should_cache_bypass(text: str) -> bool:
    """True when message looks like a content-factory trigger (stale-cache risk)."""
    if not text:
        return False
    # Scan normalized for stable matching (fullwidth etc. already folded upstream)
    has_action = any(t in text for t in _TRIGGER_ACTION)
    has_domain = any(t in text for t in _TRIGGER_DOMAIN)
    # Doc: 触发词 + 教育/内容词 — require action; domain soft-boosts false-positive control
    if has_action and has_domain:
        return True
    # Strong action alone (热点/写一篇/口播) still bypass — 误伤可接受
    strong = ("热点", "写一篇", "口播", "生成稿", "生成口播")
    return any(t in text for t in strong)


def _env_bool(name: str, default: bool = True) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _max_input_chars() -> int:
    try:
        return int(os.getenv("PIPELINE_MAX_INPUT_CHARS", "10000") or "10000")
    except ValueError:
        return 10000


def _bump_rate(tenant_id: str) -> None:
    """Cheap block still counts toward rate limit (D7); never mask GATE."""
    try:
        check_rate_limit(tenant_id)
    except Exception:
        logger.debug("preprocess rate bump failed", exc_info=True)


def _block(
    state: PipelineState,
    *,
    error_code: str,
    guard_label: str,
    gate_reason: str,
) -> PipelineState:
    state["finish_reason"] = "blocked"
    state["error_code"] = error_code
    state["response"] = _GATE_RESPONSE
    state["guardrails_passed"] = False
    state["gate_reason"] = gate_reason
    _bump_rate(state["tenant_id"])
    try:
        guardrails_blocked.labels(
            tenant=state["tenant_id"], guard=guard_label
        ).inc()
    except Exception:
        pass
    return state


@observe(name="pipeline.preprocess")
async def preprocess(state: PipelineState) -> PipelineState:
    """Normalize message, write query_hash; optional cheap GATE when enabled."""
    raw = state.get("raw_input") or state.get("message") or ""
    state["raw_input"] = raw

    normalized = normalize_text(raw)
    query_hash = make_normalized_query_hash(raw)
    state["query_hash"] = query_hash
    state["cache_bypass"] = should_cache_bypass(normalized)

    enabled = _env_bool("PIPELINE_PREPROCESS_ENABLED", True)
    if not enabled:
        state["message"] = normalized
        return state

    if not normalized:
        return _block(
            state,
            error_code="GATE_001",
            guard_label="gate_empty",
            gate_reason="empty",
        )

    if len(raw) > _max_input_chars():
        return _block(
            state,
            error_code="GATE_002",
            guard_label="gate_oversize",
            gate_reason="oversize",
        )

    hit = deny_list_hit(normalized)
    if hit:
        return _block(
            state,
            error_code="GATE_003",
            guard_label="gate_deny",
            gate_reason=f"deny:{hit}",
        )

    state["message"] = normalized
    return state


def should_gate_block(state: PipelineState) -> str:
    """Conditional edge: cheap GATE block → END."""
    if state.get("finish_reason") == "blocked" and str(
        state.get("error_code") or ""
    ).startswith("GATE_"):
        return "end"
    return "continue"
