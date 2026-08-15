"""task_plan 咨询性脚手架节点（Task 43.1）— fail-soft，不进 Workflow 执行。"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from backend.core.audit import write_audit_sync
from backend.core.auth.models import TenantContext
from backend.core.capability.invoke import capability_visible_to
from backend.core.capability.registry import get_capability_registry
from backend.core.guardrails.output_guard import check_output
from backend.core.harness import LLMHarness
from backend.core.workflow.ir import _FORBIDDEN_PARAM_KEYS, validate_params_against_spec
from backend.observability.decorators import enrich_span, observe
from backend.pipeline.intent_path import (
    resolve_short_path_skill,
    should_task_plan,
    skill_to_state,
)
from backend.pipeline.state import PipelineState

logger = logging.getLogger(__name__)
harness = LLMHarness()

_DEFAULT_MAX_TOKENS = 800
_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _max_tokens() -> int:
    raw = (os.getenv("TASK_PLAN_MAX_TOKENS") or "").strip()
    if not raw:
        return _DEFAULT_MAX_TOKENS
    try:
        return max(64, min(4000, int(raw)))
    except ValueError:
        return _DEFAULT_MAX_TOKENS


def _tenant_from_state(state: PipelineState) -> TenantContext:
    uc = state.get("user_context") or {}
    return TenantContext(
        tenant_id=str(state.get("tenant_id") or uc.get("tenant_id") or ""),
        user_id=str(state.get("user_id") or uc.get("user_id") or ""),
        role=str(uc.get("role") or "user"),
        extra_permissions=list(uc.get("permissions") or []),
        is_cross_tenant=bool(uc.get("is_cross_tenant")),
        business_roles=list(uc.get("business_roles") or []) or None,
    )


def _list_visible_capabilities(state: PipelineState) -> list[dict[str, Any]]:
    tenant = _tenant_from_state(state)
    reg = get_capability_registry()
    items: list[dict[str, Any]] = []
    for spec in reg.list(include_disabled=False):
        if not capability_visible_to(spec, tenant):
            continue
        items.append(
            {
                "id": spec.id,
                "name": getattr(spec, "name", spec.id),
                "kind": str(getattr(spec, "kind", "") or ""),
                "permission": getattr(spec, "permission", None),
                "param_spec": getattr(spec, "param_spec", None) or {},
            }
        )
    return items


def validate_task_plan(
    plan: dict[str, Any],
    *,
    caps_by_id: dict[str, dict[str, Any]] | None = None,
) -> None:
    """轻量校验：禁完整 WorkflowIR.model_validate；复用 forbidden + param_spec。"""
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("task_plan.steps must be a non-empty list")
    caps_by_id = caps_by_id or {}
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"step[{i}] must be object")
        cap_id = step.get("capability_id")
        if not isinstance(cap_id, str) or not cap_id.strip():
            raise ValueError(f"step[{i}] missing capability_id")
        params = step.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError(f"step[{i}] params must be object")
        bad = set(params) & _FORBIDDEN_PARAM_KEYS
        if bad:
            raise ValueError(f"step[{i}] forbidden keys: {sorted(bad)}")
        meta = caps_by_id.get(cap_id)
        if meta is not None:
            validate_params_against_spec(params, meta.get("param_spec") or {})


def _parse_plan_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = _JSON_RE.search(raw)
        if not m:
            raise ValueError("no json object in llm output") from None
        data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError("plan root must be object")
    return data


def _build_messages(
    *,
    message: str,
    intent: str,
    confidence: float,
    caps: list[dict[str, Any]],
    skill_asset_hit: dict[str, Any] | None,
) -> list[dict[str, str]]:
    cap_lines = []
    for c in caps[:40]:
        cap_lines.append(
            f"- {c['id']}: {c.get('name') or c['id']} perm={c.get('permission') or ''}"
        )
    template = ""
    if skill_asset_hit and isinstance(skill_asset_hit, dict):
        template = str(skill_asset_hit.get("cot_template") or "")[:2000]

    system = (
        "You are a task planner for NexusAI Chat. "
        "Produce a JSON object only (no markdown) with shape:\n"
        '{"steps":[{"capability_id":"...","params":{},"decision":null}]}\n'
        "Use only capability ids from the catalog. Fail soft with empty params if unsure. "
        "Do not include secrets, api keys, code, or headers in params."
    )
    if template:
        system += f"\n\nReuse this CoT template when helpful:\n{template}"

    user = (
        f"intent={intent} confidence={confidence:.3f}\n"
        f"message={message[:2000]}\n"
        f"capabilities:\n" + ("\n".join(cap_lines) or "(none)")
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def plan_for_audit(plan: dict[str, Any]) -> dict[str, Any]:
    """审计用骨架：只留 capability_id / decision，params 恒 {}（CR 1A）。"""
    steps_out: list[dict[str, Any]] = []
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        steps_out.append(
            {
                "capability_id": step.get("capability_id"),
                "params": {},
                "decision": step.get("decision"),
            }
        )
    return {"steps": steps_out[:40]}


def audit_task_plan_on_success(state: PipelineState) -> None:
    """Chat 成功终态写 chat.task_plan（CR 4A）；幂等靠调用方只在成功出口调用一次。"""
    plan = state.get("task_plan")
    if not isinstance(plan, dict) or not plan.get("steps"):
        return
    if state.get("_task_plan_audited"):
        return
    try:
        from datetime import datetime

        blob = {
            "session_id": state.get("session_id"),
            "trace_id": state.get("trace_id"),
            "plan": plan_for_audit(plan),
        }
        write_audit_sync(
            {
                "tenant_id": state["tenant_id"],
                "user_id": state["user_id"],
                "action": "chat.task_plan",
                "trace_id": state.get("trace_id") or "",
                "input_text": "",
                "output_text": json.dumps(blob, ensure_ascii=False)[:2000],
                "model": state.get("selected_model") or "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "latency_ms": 0.0,
                "error_code": None,
                "ip_address": "",
                "user_agent": "",
                "credential_kind": None,
                "key_id": None,
                "run_id": None,
                "node_id": None,
                "created_at": datetime.utcnow(),
            }
        )
        state["_task_plan_audited"] = True  # type: ignore[typeddict-item]
    except Exception:
        logger.debug("chat.task_plan audit failed", exc_info=True)


@observe(name="pipeline.task_plan")
async def task_plan(state: PipelineState) -> PipelineState:
    """analyze → task_plan → build_context；短路径空跑；失败 → task_plan=None。"""
    state.setdefault("task_plan", None)
    state.setdefault("skill_asset_hit", None)

    try:
        skill = resolve_short_path_skill(state)
        state["short_path_skill"] = skill_to_state(skill)
        if not should_task_plan(state):
            enrich_span(metadata={"task_plan": "skipped_short_path"})
            return state

        try:
            caps = _list_visible_capabilities(state)
        except Exception:
            logger.debug("task_plan caps load failed", exc_info=True)
            state["task_plan"] = None
            return state

        # 43.2+ : 可选检索 skill_assets（失败忽略，从零 CoT）
        if not state.get("skill_asset_hit"):
            try:
                from backend.core.skill_assets.service import search_published

                hits = search_published(
                    tenant_id=state["tenant_id"],
                    query=state.get("raw_input") or state.get("message") or "",
                    limit=1,
                    user_id=state.get("user_id"),
                )
                if hits:
                    asset, score = hits[0]
                    state["skill_asset_hit"] = {
                        "id": asset.id,
                        "name": asset.name,
                        "cot_template": asset.cot_template,
                        "score": score,
                    }
                    try:
                        from backend.core.skill_assets.service import bump_usage_by_id

                        bump_usage_by_id(
                            tenant_id=state["tenant_id"],
                            asset_id=asset.id,
                        )
                    except Exception:
                        logger.debug("skill_asset usage bump skipped", exc_info=True)
            except Exception:
                logger.debug("skill_asset search skipped", exc_info=True)

        caps_by_id = {c["id"]: c for c in caps}
        message = state.get("raw_input") or state.get("message") or ""
        intent = state.get("intent", "default") or "default"
        confidence = float(state.get("intent_confidence", 0.0) or 0.0)
        messages = _build_messages(
            message=message,
            intent=intent,
            confidence=confidence,
            caps=caps,
            skill_asset_hit=state.get("skill_asset_hit"),
        )

        model = state.get("selected_model") or "deepseek-v4-flash"
        max_tokens = _max_tokens()
        prompt_meta = {
            "prompt_name": "task_plan.cot",
            "prompt_version": "1",
            "prompt_label": "builtin",
            "prompt_source": "builtin",
        }

        plan: dict[str, Any] | None = None
        last_err: str | None = None
        for _attempt in range(2):
            try:
                result = await harness.generate(
                    model=model,
                    messages=messages,
                    tenant_id=state["tenant_id"],
                    api_key=state.get("llm_api_key"),
                    base_url=state.get("llm_base_url"),
                    max_tokens=max_tokens,
                    provider=state.get("llm_key_provider") or "default",
                )
                if not result.success:
                    last_err = result.error or "llm_failed"
                    continue
                parsed = _parse_plan_json(str(result.output or ""))
                validate_task_plan(parsed, caps_by_id=caps_by_id)
                # CR 2A: plan 过 output_guardrails；blocked → 降级 None
                guard = await check_output(
                    json.dumps(parsed, ensure_ascii=False)[:4000]
                )
                if guard.action == "blocked":
                    last_err = guard.reason or "output_blocked"
                    continue
                plan = parsed
                break
            except Exception as exc:
                last_err = type(exc).__name__
                continue

        state["task_plan"] = plan
        enrich_span(
            metadata={
                "task_plan": "ok" if plan is not None else "degraded",
                "error": last_err,
                **prompt_meta,
            }
        )
        # 40.86: optional Chat → published workflow bridge (fail-soft)
        try:
            from backend.pipeline.chat_workflow_bridge import try_bridge_start_run

            state = try_bridge_start_run(state)
        except Exception:
            logger.debug("chat workflow bridge skipped", exc_info=True)
    except Exception:
        logger.debug("task_plan node failed", exc_info=True)
        state["task_plan"] = None
    return state
