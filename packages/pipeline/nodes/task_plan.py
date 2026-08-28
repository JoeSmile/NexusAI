"""task_plan 咨询性脚手架节点（Task 43.1）— fail-soft，不进 Workflow 执行。"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from backend.core.audit import write_audit_sync
from backend.core.audit_context import get_audit_lineage
from backend.core.capability.invoke import capability_visible_to
from backend.core.capability.registry import get_capability_registry
from backend.core.guardrails.output_guard import check_output
from backend.core.harness import LLMHarness
from backend.core.plan.event_bus import bus_for_state
from backend.core.plan.llm_output_guard import prevalidate_llm_plan
from backend.core.plan.models import plan_to_state_dict
from backend.core.plan.tool_index import search_capabilities
from backend.core.plan.validator import validate_plan_ir
from backend.observability.decorators import enrich_span, observe
from packages.auth.models import TenantContext
from packages.pipeline.intent_path import (
    resolve_short_path_skill,
    short_path_predicate,
    should_task_plan,
    skill_to_state,
)
from packages.pipeline.nodes.query_rewrite import attach_query_rewrite_to_plan
from packages.pipeline.state import PipelineState

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
                "description": str((spec.spec or {}).get("description") or spec.name),
            }
        )
    return items


def _plan_timeout_s() -> float:
    raw = (os.getenv("TASK_PLAN_TIMEOUT_S") or "").strip()
    if not raw:
        return 8.0
    try:
        return max(1.0, min(60.0, float(raw)))
    except ValueError:
        return 8.0


def _force_task_plan_on_stream() -> bool:
    return os.getenv("FORCE_TASK_PLAN_ON_STREAM", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _async_task_plan_on_stream_enabled() -> bool:
    """Task 70: 异步规划需显式开启，或编排开关打开（编排消费 PlanIR）。

    默认关：避免每条长路径消息都白等规划 LLM（5–8s）。FORCE 仍走图内同步（演示用）。
    """
    if os.getenv("ASYNC_TASK_PLAN_ON_STREAM", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    return os.getenv("ORCHESTRATOR_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def should_async_plan_on_stream(state: PipelineState | dict) -> bool:
    """Task 70: stream 复杂路径走异步规划（图内同步仍跳过，除非 FORCE）。"""
    if not state.get("stream_mode"):
        return False
    if not _async_task_plan_on_stream_enabled():
        return False
    if _force_task_plan_on_stream():
        # FORCE 时图内已同步规划，避免重复
        return False
    if state.get("triggered_run") or state.get("finish_reason") == "workflow_triggered":
        return False
    if state.get("task_plan"):
        return False
    if short_path_predicate(state):
        return False
    return should_task_plan(state)


def validate_task_plan(
    plan: dict[str, Any],
    *,
    caps_by_id: dict[str, dict[str, Any]] | None = None,
    fallback_goal: str = "",
) -> None:
    """PlanIR 硬校验（Task 56）；caps_by_id 必填（白名单）。"""
    if not caps_by_id:
        raise ValueError("caps_by_id required for plan validation")
    validate_plan_ir(
        prevalidate_llm_plan(plan, caps_by_id=caps_by_id),
        caps_by_id=caps_by_id,
        fallback_goal=fallback_goal,
    )


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
    session_coref: dict[str, Any] | None = None,
    agent_type_id: str | None = None,
) -> list[dict[str, str]]:
    cap_lines = []
    for c in caps:
        cap_lines.append(
            f"- {c['id']}: {c.get('name') or c['id']} perm={c.get('permission') or ''}"
        )
    template = ""
    if skill_asset_hit and isinstance(skill_asset_hit, dict):
        template = str(skill_asset_hit.get("cot_template") or "")[:2000]

    system = (
        "You are a task planner for NexusAI Chat. "
        "Produce a JSON object only (no markdown) with PlanIR shape:\n"
        '{"query_rewrite":{"rewritten_query":"...","sub_queries":[],"language":"zh",'
        '"clarification_needed":false,'
        '"coref_table":{"entries":[{"entity_id":"e1","canonical":"...",'
        '"mentions":["它"],"resolved_value":"...","confidence":0.9,"source_turn":1}]}},'
        '"goal":"...","version":1,"max_depth":3,'
        '"steps":[{"id":"s1","capability_id":"...","params":{},"depends_on":[],'
        '"mode":"serial","on_fail":"fail","post_process":[]}]}'
        "\nUse ONLY capability ids from the catalog (whitelist). "
        "depends_on must reference prior step ids; no cycles. "
        "Do not include secrets, api keys, code, or headers in params."
    )
    if template:
        system += f"\n\nReuse this CoT template when helpful:\n{template}"

    user = (
        f"intent={intent} confidence={confidence:.3f}\n"
        f"message={message[:2000]}\n"
    )
    if agent_type_id:
        from backend.core.plan.agent_type import get_agent_type

        at = get_agent_type(agent_type_id)
        if at is not None:
            user += (
                f"agent_type={at.type_id} role={at.role}\n"
                f"preferred_capabilities={','.join(at.capability_ids)}\n"
            )
    if session_coref and session_coref.get("entries"):
        user += (
            "session_coref_table="
            + json.dumps(session_coref, ensure_ascii=False)[:1500]
            + "\n"
        )
    user += "capabilities:\n" + ("\n".join(cap_lines) or "(none)")
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
                "id": step.get("id"),
                "capability_id": step.get("capability_id"),
                "depends_on": list(step.get("depends_on") or []),
                "params": {},
                "decision": step.get("decision"),
            }
        )
    out: dict[str, Any] = {"steps": steps_out[:40]}
    if plan.get("goal"):
        out["goal"] = str(plan.get("goal"))[:500]
    return out


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
        lineage = get_audit_lineage()
        plan_audit = plan_for_audit(plan)
        write_audit_sync(
            {
                "tenant_id": state["tenant_id"],
                "user_id": state["user_id"],
                "action": "chat.task_plan",
                "trace_id": state.get("trace_id") or "",
                "parent_trace_id": lineage.parent_trace_id,
                "tool_use_id": lineage.tool_use_id or f"task_plan:{state.get('trace_id')}",
                "input_text": "",
                "output_text": json.dumps(blob, ensure_ascii=False)[:2000],
                "decision_explain": json.dumps(
                    {
                        "plan": plan_audit,
                        "query_rewrite": state.get("query_rewrite"),
                        "coref_table": (state.get("query_rewrite") or {}).get("coref_table"),
                    },
                    ensure_ascii=False,
                )[:4000],
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


def _tenant_has_bridge_targets(tenant_id: str) -> bool:
    """快速预判: 租户是否有已发布且带 intent_tags 的 workflow(bridge 匹配前提)。

    08-16 性能修复: 无则 task_plan 产出无消费方,跳过规划 LLM 与检索,
    非流式长路径不再白烧一次 LLM(首 token 延迟主因之一)。
    """
    if not tenant_id:
        return False
    try:
        from backend.database.pgvector_session import Workflow, get_pg_session

        sf = get_pg_session()
        with sf.Session() as session:
            rows = (
                session.query(Workflow.intent_tags)
                .filter(
                    Workflow.tenant_id == tenant_id,
                    Workflow.status == "published",
                )
                .limit(5)
                .all()
            )
        return any(bool(tags) for (tags,) in rows)
    except Exception:
        logging.getLogger(__name__).debug(
            "bridge target precheck failed; fallback to original path",
            exc_info=True,
        )
        return True  # 保守: 预判失败按原逻辑跑,不改变行为


async def _produce_plan_ir(state: PipelineState) -> dict[str, Any] | None:
    """跑规划 LLM + 校验；失败返回 None（fail-soft）。"""
    try:
        caps = _list_visible_capabilities(state)
    except Exception:
        logger.debug("task_plan caps load failed", exc_info=True)
        return None

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

    from backend.core.plan.coref import (
        apply_coref_to_plan,
        infer_coref_table,
        invalidate_coref_if_drift,
        load_session_coref,
        merge_coref_tables,
        parse_coref_table,
        save_session_coref,
    )

    await invalidate_coref_if_drift(state)
    session_coref = load_session_coref(state)
    session_coref_dict = session_coref.model_dump(mode="json")

    ranked_caps = search_capabilities(caps, message, top_k=12)
    from backend.core.plan.agent_spawn import boost_capabilities_for_agent_type

    ranked_caps = boost_capabilities_for_agent_type(
        ranked_caps,
        str(state.get("agent_type_id") or "") or None,
    )
    messages = _build_messages(
        message=message,
        intent=intent,
        confidence=confidence,
        caps=ranked_caps,
        skill_asset_hit=state.get("skill_asset_hit"),
        session_coref=session_coref_dict if session_coref.entries else None,
        agent_type_id=str(state.get("agent_type_id") or "") or None,
    )

    model = state.get("selected_model") or "deepseek-v4-flash"
    max_tokens = _max_tokens()
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
            enriched = attach_query_rewrite_to_plan(
                parsed, original_message=message
            )
            qr_raw = enriched.get("query_rewrite") or {}
            fresh = parse_coref_table(qr_raw.get("coref_table"))
            if fresh is None or not fresh.entries:
                fresh = infer_coref_table(
                    message,
                    dict(state.get("entities") or {}),
                )
            merged_coref = merge_coref_tables(session_coref, fresh)
            enriched = apply_coref_to_plan(enriched, merged_coref)
            await save_session_coref(state, merged_coref)
            plan_ir = validate_plan_ir(
                prevalidate_llm_plan(enriched, caps_by_id=caps_by_id),
                caps_by_id=caps_by_id,
                fallback_goal=message,
            )
            plan_dict = plan_to_state_dict(plan_ir)
            guard = await check_output(
                json.dumps(plan_dict, ensure_ascii=False)[:4000]
            )
            if guard.action == "blocked":
                last_err = guard.reason or "output_blocked"
                continue
            plan = plan_dict
            state["query_rewrite"] = plan_dict.get("query_rewrite")
            break
        except Exception as exc:
            last_err = type(exc).__name__
            continue

    if plan is None and last_err:
        logger.debug("task_plan produce degraded: %s", last_err)
    return plan


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

        message_early = state.get("raw_input") or state.get("message") or ""
        # 45b: 旁路 / 关键词 bridge — 流式也要能触发（不依赖规划 LLM）
        try:
            from packages.pipeline.chat_workflow_bridge import (
                should_skip_workflow_bridge,
                try_bridge_start_run,
            )

            if should_skip_workflow_bridge(message_early):
                enrich_span(metadata={"task_plan": "bridge_bypassed"})
            else:
                state = try_bridge_start_run(state)
                if state.get("triggered_run"):
                    enrich_span(metadata={"task_plan": "bridge_triggered_early"})
                    return state
        except Exception:
            logger.debug("early chat workflow bridge skipped", exc_info=True)

        # A(08-16 / Task 70): 流式路径图内跳过同步规划——首 token 不阻塞。
        # 复杂路径改由 SSE 侧 asyncio.wait_for(8s) 异步规划（见 run_async_task_plan_for_stream）。
        # 面试演示仍可用 FORCE_TASK_PLAN_ON_STREAM=1 恢复图内同步。
        if state.get("stream_mode") and not _force_task_plan_on_stream():
            enrich_span(metadata={"task_plan": "skipped_streaming"})
            return state

        # B(08-16 性能修复): 租户无已发布带 intent_tags 的 workflow 时,
        # bridge 永不命中；图内同步规划仍跳过（异步流式规划见 run_async_task_plan_for_stream）。
        if not _tenant_has_bridge_targets(state.get("tenant_id") or ""):
            enrich_span(metadata={"task_plan": "skipped_no_bridge_target"})
            return state

        plan = await _produce_plan_ir(state)
        state["task_plan"] = plan
        enrich_span(
            metadata={
                "task_plan": "ok" if plan is not None else "degraded",
                "prompt_name": "task_plan.cot",
                "prompt_version": "1",
                "prompt_label": "builtin",
                "prompt_source": "builtin",
            }
        )
        if plan is not None:
            bus = bus_for_state(state)
            if bus is not None:
                qr = plan.get("query_rewrite") or {}
                bus.publish_plan(
                    goal=str(plan.get("goal") or ""),
                    steps=list(plan.get("steps") or []),
                    coref_table=qr.get("coref_table"),
                )
        # 40.86: optional Chat → published workflow bridge (fail-soft)
        try:
            from packages.pipeline.chat_workflow_bridge import try_bridge_start_run

            state = try_bridge_start_run(state)
        except Exception:
            logger.debug("chat workflow bridge skipped", exc_info=True)
    except Exception:
        logger.debug("task_plan node failed", exc_info=True)
        state["task_plan"] = None
    return state


async def run_async_task_plan_for_stream(
    state: PipelineState,
    *,
    timeout_s: float | None = None,
    emit_pending: bool = True,
) -> tuple[PipelineState, str]:
    """Task 70 C: SSE 侧异步规划。返回 (state, status)。

    status: skipped | ok | degraded | timeout | error

    Caller should yield ``task_plan_pending`` SSE *before* awaiting this when
    ``emit_pending=False`` (keeps TTFB for the placeholder frame).
    """
    import asyncio

    if not should_async_plan_on_stream(state):
        return state, "skipped"

    bus = bus_for_state(state)
    if emit_pending and bus is not None:
        bus.publish_task_plan_pending(
            message=str(state.get("message") or state.get("raw_input") or "")[:200]
        )

    limit = _plan_timeout_s() if timeout_s is None else float(timeout_s)
    try:
        plan = await asyncio.wait_for(_produce_plan_ir(state), timeout=limit)
    except TimeoutError:
        state["task_plan"] = None
        state["task_plan_async_status"] = "timeout"  # type: ignore[typeddict-item]
        if bus is not None:
            bus.publish_task_plan_timeout(timeout_s=limit)
        enrich_span(metadata={"task_plan": "async_timeout", "timeout_s": limit})
        return state, "timeout"
    except Exception:
        logger.debug("async task_plan failed", exc_info=True)
        state["task_plan"] = None
        state["task_plan_async_status"] = "error"  # type: ignore[typeddict-item]
        if bus is not None:
            bus.publish_task_plan_done(ok=False, reason="error")
        return state, "error"

    state["task_plan"] = plan
    if plan is None:
        state["task_plan_async_status"] = "degraded"  # type: ignore[typeddict-item]
        if bus is not None:
            bus.publish_task_plan_done(ok=False, reason="degraded")
        enrich_span(metadata={"task_plan": "async_degraded"})
        return state, "degraded"

    state["task_plan_async_status"] = "ok"  # type: ignore[typeddict-item]
    state["stream_async_plan"] = True  # type: ignore[typeddict-item]
    if bus is not None:
        qr = plan.get("query_rewrite") or {}
        bus.publish_plan(
            goal=str(plan.get("goal") or ""),
            steps=list(plan.get("steps") or []),
            coref_table=qr.get("coref_table"),
        )
        bus.publish_task_plan_done(ok=True, goal=str(plan.get("goal") or ""))
    enrich_span(metadata={"task_plan": "async_ok"})

    try:
        from packages.pipeline.nodes.orchestrator import (
            orchestrator,
            should_run_orchestrator,
        )

        if should_run_orchestrator(state):
            state = await orchestrator(state)
    except Exception:
        logger.debug("async stream orchestrator skipped", exc_info=True)

    return state, "ok"
