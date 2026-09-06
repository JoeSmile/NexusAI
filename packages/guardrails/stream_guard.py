"""Streaming output guard — isomorphic with ``sanitize_generation_exit``.

Chunk path: G7 redact + edu redlines (replace, continue) + profile drift / key BLOCK.
Already-sent text is not rewritten; incomplete name/redline prefixes are held back.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from packages.guardrails.edu_marketing import REDLINE_SOURCE_TERMS, apply_edu_marketing_redlines
from packages.guardrails.generation_exit import VALID_PROFILES, resolve_output_guard_profile
from packages.guardrails.output_guard import OUTPUT_BLOCK_PATTERNS, match_role_drift
from packages.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

STREAM_BLOCK_PLACEHOLDER = "该回复因命中内容安全规则已停止生成。"


def student_names_from_warm(warm: dict[str, Any] | None) -> list[str]:
    names: list[str] = []
    for key, raw in (warm or {}).items():
        if not str(key).startswith("entity:"):
            continue
        try:
            val = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue
        if not isinstance(val, dict):
            continue
        if str(val.get("relation") or "") not in ("学生", "学员"):
            continue
        name = str(val.get("name") or val.get("text") or "").strip()
        if name:
            names.append(name)
    names.sort(key=len, reverse=True)
    return names


def apply_stream_block_to_state(state: PipelineState, *, reason: str) -> PipelineState:
    state["response"] = STREAM_BLOCK_PLACEHOLDER
    state["finish_reason"] = "blocked"
    state["error_code"] = "GUARD_003"
    return state


def stream_block_audit_record(
    state: PipelineState, *, reason: str, profile: str
) -> dict[str, Any]:
    return {
        "tenant_id": state["tenant_id"],
        "user_id": state["user_id"],
        "action": "guardrails.stream_block",
        "trace_id": str(state.get("trace_id") or ""),
        "input_text": str(state.get("message") or "")[:200],
        "output_text": json.dumps(
            {"reason": reason, "profile": profile},
            ensure_ascii=False,
        )[:4000],
        "model": "stream_guard",
    }


def _hold_needles(names: list[str]) -> list[str]:
    out = [n for n in names if n]
    out.extend(REDLINE_SOURCE_TERMS)
    out.sort(key=len, reverse=True)
    return out


def suffix_hold_len(text: str, names: list[str]) -> int:
    """Chars at the end that are a proper prefix of a name or redline term."""
    if not text:
        return 0
    hold = 0
    for needle in _hold_needles(names):
        if needle in text:
            continue
        max_k = min(len(needle) - 1, len(text))
        for k in range(max_k, 0, -1):
            if text.endswith(needle[:k]):
                hold = max(hold, k)
                break
    return hold


def remaining_pending(clean_so_far: str, pending: str, names: list[str]) -> str:
    if not pending:
        return ""
    hold = suffix_hold_len(clean_so_far + pending, names)
    if hold <= 0:
        return ""
    return pending[-min(hold, len(pending)) :]


def _block_reason(body: str, profile: str) -> str:
    for pattern in OUTPUT_BLOCK_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            return f"blocked:sensitive_content:{pattern}"
    hit = match_role_drift(body, profile=profile)
    if hit:
        return f"blocked:role_drift:{hit}"
    return ""


def sanitize_streaming_chunk(
    *,
    clean_so_far: str,
    new_chunk: str,
    tenant_id: str,
    profile: str | None,
    names: list[str],
    max_chars: int = 4000,
) -> tuple[str, str]:
    """Return (yieldable_delta, reason). reason: '' | length_retracted | blocked:..."""
    resolved = profile if profile in VALID_PROFILES else resolve_output_guard_profile(tenant_id)
    working = (clean_so_far or "") + (new_chunk or "")
    hold = suffix_hold_len(working, names)
    confirmed = working[:-hold] if hold else working
    if len(confirmed) < len(clean_so_far):
        return "", ""

    body = confirmed
    try:
        from packages.memory.memory_service import redact_student_names_in_text

        body = redact_student_names_in_text(
            body, tenant_id=tenant_id or "", names=names
        )
    except Exception:
        logger.debug("stream_guard G7 skipped", exc_info=True)

    try:
        body, _hits = apply_edu_marketing_redlines(body)
    except Exception:
        logger.debug("stream_guard marketing skipped", exc_info=True)

    blocked = _block_reason(body, resolved)
    if blocked:
        return "", blocked

    retracted = False
    if max_chars is not None and len(body) > max_chars:
        body = body[:max_chars]
        retracted = True

    if not body.startswith(clean_so_far):
        return "", "blocked:output_rewrite"

    delta = body[len(clean_so_far) :]
    return delta, ("length_retracted" if retracted else "")
