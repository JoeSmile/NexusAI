"""PlanIR 动态执行器（Task 56 切片 3）。"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from backend.core.audit_context import bind_audit_lineage
from backend.core.auth.models import TenantContext
from backend.core.capability.invoke import invoke
from backend.core.harness import LLMHarness
from backend.core.plan.blackboard import Blackboard, entry_from_step_result
from backend.core.plan.event_bus import PlanEventBus, bus_for_state
from backend.core.plan.execution import group_independent_batches
from backend.core.plan.llm_output_guard import prevalidate_llm_plan
from backend.core.plan.loop_guard import LoopGuard, LoopGuardError
from backend.core.plan.models import OnFailMode, PlanIR, PlanStep
from backend.core.plan.params_resolve import resolve_step_params
from backend.core.plan.spawn_budget import SpawnBudget, resolve_spawn_budget
from backend.core.plan.tool_output_guard import sanitize_tool_output
from backend.core.plan.validator import topological_sort_steps, validate_plan_ir
from backend.observability.decorators import enrich_span, observe
from backend.pipeline.nodes.task_plan import _list_visible_capabilities, _tenant_from_state
from backend.pipeline.state import PipelineState

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
    """experiment_hook 之后：有 PlanIR 且开关打开时走编排。"""
    if not orchestrator_enabled():
        return False
    if state.get("triggered_run") or state.get("finish_reason") == "workflow_triggered":
        return False
    if state.get("short_path_skill"):
        return False
    if not state.get("task_plan"):
        return False
    if state.get("stream_mode"):
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
) -> dict[str, Any]:
    payload = resolve_step_params(dict(step.params), step_results, state=state)
    if loop_guard is not None and state is not None:
        loop_guard.check(
            step.capability_id,
            payload,
            tenant_id=state.get("tenant_id") or "",
            user_id=state.get("user_id") or "",
            trace_id=str(state.get("trace_id") or ""),
        )
        loop_guard.persist(state)  # type: ignore[arg-type]
    outcome = await _collect_invoke(step.capability_id, payload, tenant)
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
    prompt = (
        "Replan remaining steps after failure. Return JSON only.\n"
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
) -> str:
    if blackboard is not None and blackboard.list_entries():
        return blackboard.synthesize(plan.goal)
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
) -> tuple[dict[str, Any], PlanIR, int]:
    """执行 PlanIR；返回 (step_results, 可能更新后的 plan, spawn_total)。"""
    budget = budget or resolve_spawn_budget()
    tenant = _tenant_from_state(state)
    step_results: dict[str, Any] = dict(state.get("step_results") or {})
    spawn_total = int(spawn_total or state.get("orchestrator_spawn_total") or 0)
    current_plan = plan
    bus = bus_for_state(state)
    blackboard = Blackboard.from_state(state)
    doc_refs = [str(x) for x in (state.get("rag_retrieved_ids") or [])]
    loop_guard = LoopGuard.from_pipeline(state)

    while True:
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
                try:
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
                    if entry is not None:
                        blackboard.add(
                            entry,
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
                except LoopGuardError as e:
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
                    err = str(e)
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
                                reason=err,
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
        state["response"] = _synthesize_response(plan, partial, blackboard=bb)
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
        final_plan, step_results, blackboard=blackboard
    )
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
    """编排后：replan 超限走 model_router；否则直接收尾。"""
    if state.get("finish_reason") == "routed_to_llm":
        return "model_router"
    return "conversion_hook"
