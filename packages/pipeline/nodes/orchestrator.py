"""PlanIR 动态执行器（Task 56 切片 3）。"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from packages.audit_context import bind_audit_lineage
from packages.capability.invoke import invoke
from packages.harness import LLMHarness
from packages.plan.agent_spawn import (
    SpawnBlockedError,
    complete_agent_instance_for_step,
    fail_agent_instance_for_step,
    prepare_orchestrator_spawn,
    resolve_step_tenant,
    spawn_sub_agent_instance,
)
from packages.plan.blackboard import Blackboard, entry_from_step_result
from packages.plan.clarification import (
    hold_for_clarification,
)
from packages.plan.event_bus import PlanEventBus, bus_for_state
from packages.plan.execution import group_independent_batches
from packages.plan.intent_drift import (
    DriftAssessment,
    audit_intent_drift,
    detect_intent_drift,
)
from packages.plan.llm_output_guard import prevalidate_llm_plan
from packages.plan.loop_guard import LoopGuard, LoopGuardError
from packages.plan.models import OnFailMode, PlanIR, PlanStep
from packages.plan.params_resolve import resolve_step_params
from packages.plan.run_cancel import RunCancelledError, check_cancelled
from packages.plan.slot_gate import evaluate_required_slots
from packages.plan.spawn_budget import SpawnBudget, resolve_spawn_budget
from packages.plan.tool_output_guard import sanitize_tool_output
from packages.plan.validator import topological_sort_steps, validate_plan_ir
from packages.render.directive import extract_render_directive, render_directive_to_dict
from backend.observability.decorators import enrich_span, observe
from packages.auth.models import TenantContext
from packages.auth.subagent import is_sub_agent
from packages.pipeline.nodes.task_plan import _list_visible_capabilities, _tenant_from_state
from packages.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

MAX_REPLANS = 2
_ORCHESTRATOR_TIMEOUT_S = 120.0
_harness = LLMHarness()


class OrchestratorError(Exception):
    """编排执行失败（on_fail=fail 或整体熔断）。"""


def orchestrator_enabled() -> bool:
    return os.getenv("ORCHESTRATOR_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def should_run_orchestrator(state: PipelineState) -> bool:
    """experiment_hook 之后：有 PlanIR 且开关打开时走编排。

    Task 70: 流式默认仍跳过；异步规划成功后设 ``stream_async_plan`` 允许编排。
    """
    if not orchestrator_enabled():
        return False
    if state.get("triggered_run") or state.get("finish_reason") == "workflow_triggered":
        return False
    if state.get("short_path_skill"):
        return False
    if not state.get("task_plan"):
        return False
    if state.get("stream_mode") and not state.get("stream_async_plan"):
        return False
    return True


async def _collect_invoke(
    cap_id: str,
    payload: dict[str, Any],
    tenant: TenantContext,
) -> dict[str, Any]:
    chunks: list[str] = []
    cost_source = "harness"
    done_meta: dict[str, Any] = {}
    upstream: str | None = None
    async for frame in invoke(cap_id, payload, tenant):
        if frame.get("event") == "token":
            chunks.append(str(frame.get("data") or ""))
        if frame.get("cost_source"):
            cost_source = str(frame["cost_source"])
        data = frame.get("data")
        if (
            frame.get("event") == "usage"
            and isinstance(data, dict)
            and data.get("upstream")
        ):
            upstream = str(data["upstream"])
        if frame.get("event") == "done" and isinstance(data, dict):
            done_meta = data
            if data.get("upstream"):
                upstream = str(data["upstream"])
    text = "".join(chunks)
    return {
        "ok": True,
        "output": text,
        "text": text,
        "capability_id": cap_id,
        "cost_source": cost_source,
        "meta": done_meta,
        "upstream": upstream,
    }


async def _run_step_once(
    step: PlanStep,
    *,
    step_results: dict[str, Any],
    tenant: TenantContext,
    state: PipelineState | None = None,
    loop_guard: LoopGuard | None = None,
    bus: PlanEventBus | None = None,
    attempt: int = 1,
    max_attempts: int = 1,
) -> dict[str, Any]:
    base_params = dict(step.params)
    if step.sub_query and "message" not in base_params and "query" not in base_params:
        base_params["message"] = step.sub_query
    payload = resolve_step_params(base_params, step_results, state=state)
    model_name: str | None = None
    escalated_model: str | None = None
    if attempt > 1:
        payload["_orchestrator_retry_attempt"] = attempt
        from packages.capability.registry import get_capability_registry
        from backend.core.model_registry import resolve_model_for_retry

        try:
            spec = get_capability_registry().get(
                step.capability_id,
                require_enabled=False,
            )
            base_model = str(spec.spec.get("model") or spec.name)
            model_name, escalated_model = resolve_model_for_retry(base_model, attempt)
            if escalated_model:
                payload["_model_override"] = escalated_model
        except Exception:
            pass
    invoke_tenant = tenant
    instance = None
    if state is not None:
        invoke_tenant = resolve_step_tenant(
            state,
            step_capability_id=step.capability_id,
            parent=tenant,
            step_id=step.id,
        )
        if is_sub_agent(invoke_tenant):
            task = step.sub_query or str(state.get("message") or "")[:500]
            instance = spawn_sub_agent_instance(
                state,
                step_id=step.id,
                capability_id=step.capability_id,
                task=task,
                attempt=attempt,
                max_attempts=max_attempts,
                model_name=model_name,
                escalated_model=escalated_model,
            )
            if instance is not None:
                bind_audit_lineage(
                    trace_id=instance.trace_id,
                    parent_trace_id=instance.parent_run_id,
                    run_id=instance.instance_id,
                    node_id=step.id,
                )
                if bus is not None:
                    bus.emit(
                        "agent_spawn",
                        {
                            "agent_type": instance.agent_type_id,
                            "instance_id": instance.instance_id,
                            "trace_id": instance.trace_id,
                            "parent_run_id": instance.parent_run_id,
                            "step_id": step.id,
                            "capability_id": step.capability_id,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "model_name": instance.model_name,
                            "escalated_model": instance.escalated_model,
                            "status": instance.status,
                        },
                    )
    if loop_guard is not None and state is not None:
        loop_guard.check(
            step.capability_id,
            payload,
            tenant_id=state.get("tenant_id") or "",
            user_id=state.get("user_id") or "",
            trace_id=str(state.get("trace_id") or ""),
        )
        loop_guard.persist(state)  # type: ignore[arg-type]
    try:
        outcome = await _collect_invoke(step.capability_id, payload, invoke_tenant)
    except Exception as exc:
        if instance is not None and state is not None:
            fail_agent_instance_for_step(state, instance, str(exc))
        raise
    if instance is not None and state is not None:
        complete_agent_instance_for_step(state, instance, outcome)
    text = str(outcome.get("text") or outcome.get("output") or "")
    sanitized = sanitize_tool_output(text)
    if sanitized != text:
        outcome = {**outcome, "text": sanitized, "output": sanitized}
    return outcome


async def _run_step_with_retry(
    step: PlanStep,
    *,
    step_results: dict[str, Any],
    tenant: TenantContext,
    bus: PlanEventBus | None = None,
    state: PipelineState | None = None,
    loop_guard: LoopGuard | None = None,
) -> dict[str, Any]:
    retry = step.retry
    max_attempts = 1 + (retry.max if step.on_fail == OnFailMode.RETRY and retry else 0)
    backoff = float(retry.backoff_s if retry else 1.0)
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await _run_step_once(
                step,
                step_results=step_results,
                tenant=tenant,
                state=state,
                loop_guard=loop_guard if attempt == 0 else None,
                bus=bus,
                attempt=attempt + 1,
                max_attempts=max_attempts,
            )
        except Exception as e:
            last_err = e
            if attempt + 1 < max_attempts:
                if bus is not None:
                    bus.publish_retry(
                        step.id,
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                    )
                await asyncio.sleep(backoff * (attempt + 1))
    raise last_err or OrchestratorError(f"step {step.id} failed")


async def _replan_remaining(
    state: PipelineState,
    *,
    failed_step: PlanStep,
    error: str,
    executed_ids: set[str],
    plan: PlanIR,
    drift: DriftAssessment | None = None,
) -> PlanIR | None:
    count = int(state.get("orchestrator_replan_count") or 0) + 1
    state["orchestrator_replan_count"] = count  # type: ignore[typeddict-item]
    if count > MAX_REPLANS:
        state["finish_reason"] = "routed_to_llm"
        state["orchestrator_error"] = error[:500]  # type: ignore[typeddict-item]
        return None

    remaining = [s for s in plan.steps if s.id not in executed_ids]
    if not remaining:
        return None

    caps = _list_visible_capabilities(state)
    caps_by_id = {c["id"]: c for c in caps}
    drift_block = ""
    if drift is not None:
        drift_block = (
            f"intent_drift_signal: {drift.signal}\n"
            f"intent_drift_detail: {drift.detail}\n"
        )
    prompt = (
        "Replan remaining steps after failure. Return JSON only.\n"
        f"{drift_block}"
        f"goal: {plan.goal}\n"
        f"failed_step: {failed_step.id} ({failed_step.capability_id})\n"
        f"error: {error[:500]}\n"
        f"remaining_ids: {[s.id for s in remaining]}\n"
        f"capabilities: {[c['id'] for c in caps[:10]]}\n"
        'shape: {"goal":"...","steps":[{"id":"...","capability_id":"...","params":{},'
        '"depends_on":[],"mode":"serial","on_fail":"fail"}]}'
    )
    try:
        result = await _harness.generate(
            model=(os.getenv("LLM_MODEL") or "").strip() or "mock-local",
            messages=[{"role": "user", "content": prompt}],
            tenant_id=state["tenant_id"],
            max_tokens=800,
        )
        if not result.success or not result.output:
            return None
        import json
        import re

        raw = result.output.strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return None
        new_plan_raw = json.loads(m.group(0))
        new_plan_raw["goal"] = plan.goal
        validated = validate_plan_ir(
            prevalidate_llm_plan(new_plan_raw, caps_by_id=caps_by_id),
            caps_by_id=caps_by_id,
            fallback_goal=plan.goal,
        )
        # 保留已完成步骤结果，仅替换未执行部分
        merged_steps = [s for s in plan.steps if s.id in executed_ids]
        merged_steps.extend(validated.steps)
        return PlanIR(
            goal=plan.goal,
            steps=merged_steps,
            max_depth=plan.max_depth,
            version=1,
            query_rewrite=plan.query_rewrite,
        )
    except Exception:
        logger.debug("orchestrator replan failed", exc_info=True)
        return None


def _caps_index(state: PipelineState) -> dict[str, dict[str, Any]]:
    caps = _list_visible_capabilities(state)
    return {c["id"]: c for c in caps}


def _synthesize_response(
    plan: PlanIR,
    step_results: dict[str, Any],
    *,
    blackboard: Blackboard | None = None,
    state: PipelineState | None = None,
) -> str:
    if blackboard is not None and blackboard.list_entries():
        seen = set(state.get("seen_fact_ids") or []) if state is not None else set()
        text, newly_seen = blackboard.synthesize(plan.goal, seen_fact_ids=seen)
        if state is not None and newly_seen:
            merged = blackboard.mark_seen(seen, newly_seen)
            state["seen_fact_ids"] = list(merged)  # type: ignore[typeddict-item]
        return text
    parts: list[str] = []
    if plan.goal:
        parts.append(f"目标：{plan.goal}")
    for step in plan.steps:
        res = step_results.get(step.id)
        if not isinstance(res, dict):
            continue
        if res.get("skipped"):
            parts.append(f"- {step.id} ({step.capability_id}): skipped")
            continue
        text = str(res.get("output") or res.get("text") or "")[:2000]
        parts.append(f"- {step.id} ({step.capability_id}): {text}")
    return "\n".join(parts) if parts else "编排执行完成。"


async def execute_plan_ir(
    state: PipelineState,
    plan: PlanIR,
    *,
    budget: SpawnBudget | None = None,
    spawn_total: int = 0,
) -> tuple[dict[str, Any], PlanIR, int, Blackboard]:
    """执行 PlanIR；返回 (step_results, plan, spawn_total, blackboard)。"""
    budget = budget or resolve_spawn_budget()
    tenant = _tenant_from_state(state)
    step_results: dict[str, Any] = dict(state.get("step_results") or {})
    spawn_total = int(spawn_total or state.get("orchestrator_spawn_total") or 0)
    current_plan = plan
    bus = bus_for_state(state)
    blackboard = Blackboard.from_state(state)
    prepare_orchestrator_spawn(state, blackboard)
    doc_refs = [str(x) for x in (state.get("rag_retrieved_ids") or [])]
    loop_guard = LoopGuard.from_pipeline(state)

    while True:
        check_cancelled(str(state.get("trace_id") or ""))
        executed_ids = set(step_results.keys())
        steps_dicts = [s.model_dump(mode="json") for s in current_plan.steps]
        pending = [s for s in current_plan.steps if s.id not in executed_ids]
        if not pending:
            break

        topo_ids = topological_sort_steps(steps_dicts)
        by_id = {s.id: s for s in current_plan.steps}
        ordered_pending = [by_id[sid] for sid in topo_ids if sid in {p.id for p in pending}]
        batches = group_independent_batches(
            [s.model_dump(mode="json") for s in ordered_pending]
        )
        replanned = False

        for batch in batches:
            batch_steps = [by_id[str(s["id"])] for s in batch]
            parallel_width = len(batch_steps)
            use_parallel = parallel_width > 1 and budget.can_spawn(
                depth=parallel_width, spawned_total=spawn_total
            )

            async def _execute_step(step: PlanStep) -> None:
                nonlocal current_plan, replanned
                check_cancelled(str(state.get("trace_id") or ""))
                if step.id in step_results:
                    return
                if bus is not None:
                    bus.publish_step(
                        step.id,
                        capability_id=step.capability_id,
                        status="running",
                    )
                bind_audit_lineage(
                    trace_id=str(state.get("trace_id") or ""),
                    parent_trace_id=str(state.get("trace_id") or ""),
                    tool_use_id=f"{state.get('trace_id')}:{step.id}",
                    node_id=step.id,
                )
                pending_id: str | None = None
                try:
                    pending_id = blackboard.begin_pending(
                        topic=f"step.{step.id}",
                        fact_content="…",
                        source_agent_id=f"{step.id}:{step.capability_id}",
                        confidence=0.5,
                        tenant_id=state["tenant_id"],
                        user_id=state["user_id"],
                        trace_id=str(state.get("trace_id") or ""),
                    )
                    outcome = await _run_step_with_retry(
                        step,
                        step_results=step_results,
                        tenant=tenant,
                        bus=bus,
                        state=state,
                        loop_guard=loop_guard,
                    )
                    step_results[step.id] = outcome
                    entry = entry_from_step_result(
                        step_id=step.id,
                        capability_id=step.capability_id,
                        outcome=outcome,
                        document_ids_ref=doc_refs,
                    )
                    if entry is not None and pending_id:
                        blackboard.complete_entry(
                            pending_id,
                            fact_content=entry.fact_content,
                            confidence=entry.confidence,
                            document_ids_ref=entry.document_ids_ref,
                            tenant_id=state["tenant_id"],
                            user_id=state["user_id"],
                            trace_id=str(state.get("trace_id") or ""),
                        )
                    elif pending_id:
                        blackboard.fail_entry(
                            pending_id,
                            error="empty_step_output",
                            tenant_id=state["tenant_id"],
                            user_id=state["user_id"],
                            trace_id=str(state.get("trace_id") or ""),
                        )
                    if bus is not None:
                        summary = str(
                            outcome.get("output") or outcome.get("text") or ""
                        )[:200]
                        bus.publish_step(
                            step.id,
                            capability_id=step.capability_id,
                            status="succeeded",
                            summary=summary,
                        )
                    drift = detect_intent_drift(
                        goal=current_plan.goal,
                        user_message=str(state.get("message") or ""),
                        step=step,
                        outcome=outcome,
                    )
                    if drift is not None:
                        audit_intent_drift(
                            tenant_id=state["tenant_id"],
                            user_id=state["user_id"],
                            trace_id=str(state.get("trace_id") or ""),
                            assessment=drift,
                        )
                        if drift.signal == "user_correction":
                            from packages.plan.coref import clear_session_coref

                            await clear_session_coref(state)
                        new_plan = await _replan_remaining(
                            state,
                            failed_step=step,
                            error=drift.detail,
                            executed_ids=set(step_results.keys()),
                            plan=current_plan,
                            drift=drift,
                        )
                        if new_plan is not None and bus is not None:
                            bus.publish_replan(
                                reason="intent_drift",
                                detail=drift.detail,
                                new_steps=[
                                    {
                                        "id": s.id,
                                        "capability_id": s.capability_id,
                                    }
                                    for s in new_plan.steps
                                    if s.id not in step_results
                                ],
                            )
                            bus.publish_plan(
                                goal=new_plan.goal,
                                steps=[
                                    s.model_dump(mode="json") for s in new_plan.steps
                                ],
                            )
                            current_plan = new_plan
                            replanned = True
                            return
                except LoopGuardError as e:
                    if pending_id:
                        blackboard.fail_entry(
                            pending_id,
                            error=e.detail[:200],
                            tenant_id=state["tenant_id"],
                            user_id=state["user_id"],
                            trace_id=str(state.get("trace_id") or ""),
                        )
                    step_results[step.id] = {
                        "ok": False,
                        "loop_guard": True,
                        "error": e.detail,
                        "capability_id": step.capability_id,
                    }
                    if bus is not None:
                        bus.publish_step(
                            step.id,
                            capability_id=step.capability_id,
                            status="failed",
                            summary=e.detail[:200],
                        )
                    state["finish_reason"] = "loop_guard"
                    state["response"] = e.detail  # type: ignore[typeddict-item]
                    raise OrchestratorError(e.detail) from e
                except Exception as e:
                    if pending_id:
                        blackboard.fail_entry(
                            pending_id,
                            error=str(e)[:200],
                            tenant_id=state["tenant_id"],
                            user_id=state["user_id"],
                            trace_id=str(state.get("trace_id") or ""),
                        )
                    err = str(e)
                    drift = detect_intent_drift(
                        goal=current_plan.goal,
                        user_message=str(state.get("message") or ""),
                        step=step,
                        error=err,
                    )
                    if drift is not None:
                        audit_intent_drift(
                            tenant_id=state["tenant_id"],
                            user_id=state["user_id"],
                            trace_id=str(state.get("trace_id") or ""),
                            assessment=drift,
                        )
                    if step.on_fail == OnFailMode.SKIP:
                        step_results[step.id] = {
                            "ok": False,
                            "skipped": True,
                            "error": err[:500],
                            "capability_id": step.capability_id,
                        }
                        if bus is not None:
                            bus.publish_step(
                                step.id,
                                capability_id=step.capability_id,
                                status="skipped",
                                summary=err[:200],
                            )
                        return
                    if step.on_fail == OnFailMode.REPLAN:
                        new_plan = await _replan_remaining(
                            state,
                            failed_step=step,
                            error=err,
                            executed_ids=set(step_results.keys()),
                            plan=current_plan,
                            drift=drift,
                        )
                        if new_plan is None:
                            if state.get("finish_reason") == "routed_to_llm":
                                if bus is not None:
                                    bus.publish_step(
                                        step.id,
                                        capability_id=step.capability_id,
                                        status="failed",
                                        summary=err[:200],
                                    )
                                raise OrchestratorError("replan limit exceeded")
                            raise OrchestratorError(err)
                        if bus is not None:
                            bus.publish_replan(
                                reason="intent_drift" if drift else err[:500],
                                detail=drift.detail if drift else None,
                                new_steps=[
                                    {
                                        "id": s.id,
                                        "capability_id": s.capability_id,
                                    }
                                    for s in new_plan.steps
                                    if s.id not in step_results
                                ],
                            )
                            bus.publish_plan(
                                goal=new_plan.goal,
                                steps=[
                                    s.model_dump(mode="json") for s in new_plan.steps
                                ],
                            )
                        current_plan = new_plan
                        replanned = True
                        return
                    if bus is not None:
                        bus.publish_step(
                            step.id,
                            capability_id=step.capability_id,
                            status="failed",
                            summary=err[:200],
                        )
                    raise OrchestratorError(err) from e

            if use_parallel:
                spawn_total += parallel_width
                outcomes = await asyncio.gather(
                    *[_execute_step(s) for s in batch_steps],
                    return_exceptions=True,
                )
                if replanned:
                    break
                for out in outcomes:
                    if isinstance(out, Exception):
                        raise out
            else:
                for step in batch_steps:
                    spawn_total += 1
                    await _execute_step(step)
                    if replanned:
                        break
            if replanned:
                break

        if replanned:
            continue
        break

    blackboard.fail_stale_pending(
        error="run_ended_incomplete",
        tenant_id=state["tenant_id"],
        user_id=state["user_id"],
        trace_id=str(state.get("trace_id") or ""),
    )
    return step_results, current_plan, spawn_total, blackboard


@observe(name="pipeline.orchestrator")
async def orchestrator(state: PipelineState) -> PipelineState:
    """执行 task_plan 产出的 PlanIR；失败可降级长路径 LLM。"""
    if not should_run_orchestrator(state):
        return state

    raw_plan = state.get("task_plan")
    if not isinstance(raw_plan, dict):
        return state

    caps_by_id = _caps_index(state)
    try:
        plan = validate_plan_ir(
            raw_plan,
            caps_by_id=caps_by_id,
            fallback_goal=str(state.get("message") or ""),
        )
    except Exception as e:
        logger.info("orchestrator plan validation failed: %s", e)
        state["finish_reason"] = "routed_to_llm"
        return state

    timeout = float(
        os.getenv("ORCHESTRATOR_TIMEOUT_S") or _ORCHESTRATOR_TIMEOUT_S
    )

    try:
        step_results, final_plan, spawn_total, blackboard = await asyncio.wait_for(
            execute_plan_ir(state, plan),
            timeout=timeout,
        )
    except RunCancelledError:
        bus = bus_for_state(state)
        if bus is not None:
            bus.emit("cancelled", {"reason": "user_request"})
        state["finish_reason"] = "cancelled"
        state["error_code"] = "CHAT_CANCELLED"
        state["response"] = "请求已取消。"
        enrich_span(metadata={"path": "orchestrator_cancelled"})
        return state
    except SpawnBlockedError as e:
        payload = getattr(e, "payload", None) or evaluate_required_slots(state)
        if payload is not None:
            await hold_for_clarification(state, payload)
            enrich_span(metadata={"path": "orchestrator_spawn_clarify"})
            return state
        state["finish_reason"] = "routed_to_llm"
        state["orchestrator_error"] = str(e)[:500]  # type: ignore[typeddict-item]
        state["response"] = str(e)
        enrich_span(metadata={"path": "orchestrator_spawn_blocked"})
        return state
    except OrchestratorError as e:
        if state.get("finish_reason") == "routed_to_llm":
            enrich_span(metadata={"path": "orchestrator_replan_fallback"})
            return state
        if state.get("finish_reason") == "loop_guard":
            state["response"] = str(state.get("response") or e)
            enrich_span(metadata={"path": "orchestrator_loop_guard"})
            return state
        state["finish_reason"] = "error"
        state["error_code"] = "ORCH_001"
        state["response"] = f"编排执行失败: {e!s}"
        enrich_span(metadata={"path": "orchestrator_failed", "error": str(e)})
        return state
    except TimeoutError:
        partial = state.get("step_results") or {}
        bb = Blackboard.from_state(state)
        state["response"] = _synthesize_response(
            plan, partial, blackboard=bb, state=state
        )
        directive = extract_render_directive(partial)
        if directive is not None:
            state["render_directive"] = render_directive_to_dict(directive)
        state["finish_reason"] = "orchestrated"
        state["orchestrator_timeout"] = True  # type: ignore[typeddict-item]
        enrich_span(metadata={"path": "orchestrator_timeout"})
        return state
    except Exception as e:
        logger.exception("orchestrator unexpected failure")
        state["finish_reason"] = "routed_to_llm"
        state["orchestrator_error"] = str(e)[:500]  # type: ignore[typeddict-item]
        return state

    if state.get("finish_reason") == "routed_to_llm":
        enrich_span(metadata={"path": "orchestrator_replan_fallback"})
        return state

    state["step_results"] = step_results
    state["task_plan"] = final_plan.model_dump(mode="json")
    state["orchestrator_spawn_total"] = spawn_total  # type: ignore[typeddict-item]
    state["blackboard"] = blackboard.list_entries()
    state["response"] = _synthesize_response(
        final_plan, step_results, blackboard=blackboard, state=state
    )
    directive = extract_render_directive(step_results)
    if directive is not None:
        state["render_directive"] = render_directive_to_dict(directive)
    state["finish_reason"] = "orchestrated"
    enrich_span(
        metadata={
            "path": "orchestrator",
            "steps": len(final_plan.steps),
            "spawn_total": spawn_total,
        }
    )
    return state


def route_after_orchestrator(state: PipelineState) -> str:
    """编排后：replan 超限走 model_router；其余终态（成功/取消/澄清/失败）走 write_memory。"""
    if state.get("finish_reason") == "routed_to_llm":
        return "model_router"
    return "write_memory"
