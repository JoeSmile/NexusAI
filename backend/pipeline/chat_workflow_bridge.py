"""Chat → published workflow bridge (Task 40.86)."""

from __future__ import annotations

import logging
from typing import Any

from backend.database.pgvector_session import Workflow, get_pg_session
from backend.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

_MIN_CONFIDENCE = 0.7


def _plan_tags(plan: dict[str, Any] | None, intent: str | None) -> set[str]:
    tags: set[str] = set()
    if intent:
        tags.add(str(intent).strip().lower())
    if not plan:
        return tags
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        for key in ("capability_id", "intent", "name", "action"):
            val = step.get(key)
            if isinstance(val, str) and val.strip():
                tags.add(val.strip().lower())
    goal = plan.get("goal") or plan.get("intent")
    if isinstance(goal, str) and goal.strip():
        tags.add(goal.strip().lower())
    return {t for t in tags if t}


def match_published_workflow(
    *,
    tenant_id: str,
    plan: dict[str, Any] | None,
    intent: str | None,
    confidence: float,
) -> Workflow | None:
    """Pick published workflow with intent_tags overlapping plan tags; prefer more tags."""
    if confidence < _MIN_CONFIDENCE:
        return None
    want = _plan_tags(plan, intent)
    if not want:
        return None
    sf = get_pg_session()
    with sf.Session() as session:
        rows = (
            session.query(Workflow)
            .filter(
                Workflow.tenant_id == tenant_id,
                Workflow.status == "published",
            )
            .all()
        )
        best: Workflow | None = None
        best_score = 0
        for wf in rows:
            tags_raw = getattr(wf, "intent_tags", None) or []
            if isinstance(tags_raw, dict):
                tags_raw = list(tags_raw.keys())
            if not isinstance(tags_raw, list) or not tags_raw:
                continue
            have = {str(t).strip().lower() for t in tags_raw if str(t).strip()}
            score = len(want & have)
            if score > best_score:
                best_score = score
                best = wf
        return best if best_score > 0 else None


def try_bridge_start_run(state: PipelineState) -> PipelineState:
    """
    If plan matches a published composition workflow → start_run + triggered_run.
    Fail-soft: any error leaves state unchanged for LLM path.
    """
    try:
        if state.get("triggered_run"):
            return state
        # short path already skipped task_plan; still guard
        if state.get("finish_reason") in ("skill_executed", "cache_hit", "blocked"):
            return state
        plan = state.get("task_plan")
        conf = float(state.get("intent_confidence") or 0.0)
        wf = match_published_workflow(
            tenant_id=state["tenant_id"],
            plan=plan if isinstance(plan, dict) else None,
            intent=state.get("intent"),
            confidence=conf,
        )
        if wf is None:
            return state

        from backend.core.auth.models import TenantContext
        from backend.core.org.scope import resolve_org_scope
        from backend.core.workflow import runner as run_svc

        uc = state.get("user_context") or {}
        tenant = TenantContext(
            tenant_id=state["tenant_id"],
            user_id=state["user_id"],
            role=str(uc.get("role") or "user"),
            extra_permissions=list(uc.get("permissions") or []),
            is_cross_tenant=bool(uc.get("is_cross_tenant")),
        )
        sf = get_pg_session()
        with sf.Session() as session:
            scope = resolve_org_scope(
                session,
                tenant_id=tenant.tenant_id,
                user_id=tenant.user_id,
                platform_role=tenant.role,
                is_cross_tenant=tenant.is_cross_tenant,
            )
            asset = state.get("skill_asset_hit") or {}
            run_inputs = {
                "topic": (state.get("raw_input") or state.get("message") or "")[:500],
                "intent": state.get("intent"),
                "conversation_id": state.get("session_id"),
                "platform": (uc.get("platform") or "chat"),
                "asset_ids": [asset["id"]] if isinstance(asset, dict) and asset.get("id") else [],
            }
            started = run_svc.start_run(
                session,
                tenant=tenant,
                org_scope=scope,
                workflow_id=wf.id,
                run_inputs=run_inputs,
            )
        run_svc.schedule_execute(started["id"])
        # 6A: prevent next identical utterance from exact-hitting past LLM reply
        from backend.pipeline.exact_cache import invalidate_exact_cache

        invalidate_exact_cache(
            state["tenant_id"],
            state["user_id"],
            str(state.get("query_hash") or ""),
        )
        state["triggered_run"] = {
            "run_id": started["id"],
            "workflow_id": wf.id,
            "workflow_name": wf.name,
        }
        state["cache_bypass"] = True
        state["response"] = (
            f"正在生成（run_id={started['id']}，workflow={wf.name}）。完成后会通知你。"
        )
        state["finish_reason"] = "workflow_triggered"
        state["total_cost"] = 0.0
        return state
    except Exception:
        logger.debug("chat→workflow bridge failed; degrade to LLM", exc_info=True)
        return state
