"""Chat → published workflow bridge (Task 40.86 / 45b)."""

from __future__ import annotations

import logging
from typing import Any

from backend.database.pgvector_session import Workflow, get_pg_session
from backend.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

_MIN_CONFIDENCE = 0.7

# 45b: 旁路 — 跳过 bridge，走 LLM 即时回答
_BRIDGE_BYPASS_MARKERS = (
    "直接抓",
    "不用workflow",
    "不用工作流",
    "别走流程",
    "不走流程",
    "别走workflow",
)

# 消息启发式 → 与内置 workflow intent_tags 对齐
_MESSAGE_TAG_RULES: tuple[tuple[tuple[str, ...], frozenset[str]], ...] = (
    (
        ("抓热点", "挖热点", "相关热点", "热点选题", "帮我抓下热点", "抓一下热点"),
        frozenset({"hotspot", "抓热点", "热点", "hotspot.dig", "挖热点"}),
    ),
)


def should_skip_workflow_bridge(message: str | None) -> bool:
    msg = message or ""
    return any(m in msg for m in _BRIDGE_BYPASS_MARKERS)


def message_intent_tags(message: str | None) -> set[str]:
    msg = message or ""
    tags: set[str] = set()
    for needles, add in _MESSAGE_TAG_RULES:
        if any(n in msg for n in needles):
            tags |= set(add)
    # 单独「热点」过宽；仅当同时有抓/挖/选题等动作词时已覆盖
    return tags


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
    message: str | None = None,
) -> Workflow | None:
    """Pick published workflow with intent_tags overlapping plan/message tags."""
    msg_tags = message_intent_tags(message)
    # 消息强命中时放宽置信度门槛（不依赖 analyze LLM）
    eff_conf = max(float(confidence or 0.0), 0.95) if msg_tags else float(confidence or 0.0)
    if eff_conf < _MIN_CONFIDENCE:
        return None
    want = _plan_tags(plan, intent) | msg_tags
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
    If plan/message matches a published composition workflow → start_run + triggered_run.
    Fail-soft: any error leaves state unchanged for LLM path.
    """
    try:
        if state.get("triggered_run"):
            return state
        if state.get("finish_reason") in ("skill_executed", "cache_hit", "blocked"):
            return state

        message = state.get("raw_input") or state.get("message") or ""
        if should_skip_workflow_bridge(message):
            state["bridge_skipped"] = "bypass_marker"  # type: ignore[typeddict-item]
            return state

        # 确保内置热点 workflow 存在（幂等）
        try:
            from backend.core.content_ops.workflow_seed import (
                ensure_builtin_hotspot_workflow,
            )

            sf0 = get_pg_session()
            with sf0.Session() as session:
                ensure_builtin_hotspot_workflow(
                    session,
                    tenant_id=state["tenant_id"],
                    created_by=state.get("user_id") or "system",
                )
                session.commit()
        except Exception:
            logger.debug("builtin hotspot workflow seed skipped", exc_info=True)

        plan = state.get("task_plan")
        conf = float(state.get("intent_confidence") or 0.0)
        wf = match_published_workflow(
            tenant_id=state["tenant_id"],
            plan=plan if isinstance(plan, dict) else None,
            intent=state.get("intent"),
            confidence=conf,
            message=message,
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
                "topic": message[:500],
                "intent": state.get("intent"),
                "conversation_id": state.get("session_id"),
                "platform": (uc.get("platform") or "chat"),
                "asset_ids": [asset["id"]] if isinstance(asset, dict) and asset.get("id") else [],
                "adapter": "topic_agent",
                "save": True,
            }
            started = run_svc.start_run(
                session,
                tenant=tenant,
                org_scope=scope,
                workflow_id=wf.id,
                run_inputs=run_inputs,
            )
        run_svc.schedule_execute(started["id"])
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
            f"正在抓取相关热点（run_id={started['id']}，workflow={wf.name}）。"
            "完成后可在「内容库」查看今日合集。"
        )
        state["finish_reason"] = "workflow_triggered"
        state["total_cost"] = 0.0
        return state
    except Exception:
        logger.debug("chat→workflow bridge failed; degrade to LLM", exc_info=True)
        return state
