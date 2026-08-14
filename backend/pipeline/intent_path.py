"""Shared short-path / task_plan gate (Task 43).

short_path_predicate = confidence >= 0.85 AND short_path_skill is not None
should_task_plan = not short_path_predicate
"""

from __future__ import annotations

from typing import Any

from backend.pipeline.state import PipelineState
from backend.skills.base import BaseSkill
from backend.skills.registry import registry

SHORT_PATH_CONFIDENCE = 0.85


def _skill_from_state_value(raw: Any) -> BaseSkill | None:
    if raw is None:
        return None
    if isinstance(raw, BaseSkill):
        return raw
    if isinstance(raw, dict):
        sid = raw.get("id")
        if isinstance(sid, str) and sid:
            return registry.get_skill(sid)
        return None
    if isinstance(raw, str) and raw:
        return registry.get_skill(raw)
    return None


def skill_to_state(skill: BaseSkill | None) -> dict[str, str] | None:
    if skill is None:
        return None
    return {"id": skill.id, "name": getattr(skill, "name", "") or skill.id}


def resolve_short_path_skill(state: PipelineState | dict) -> BaseSkill | None:
    """与 model_router 同源：registry.get_skill_for_intent；优先复用 state 已解析结果。"""
    existing = _skill_from_state_value(state.get("short_path_skill"))
    if existing is not None:
        return existing

    intent = state.get("intent", "default") or "default"
    confidence = float(state.get("intent_confidence", 0.0) or 0.0)
    if confidence < SHORT_PATH_CONFIDENCE:
        return None
    return registry.get_skill_for_intent(intent, confidence, threshold=SHORT_PATH_CONFIDENCE)


def short_path_predicate(state: PipelineState | dict) -> bool:
    skill = resolve_short_path_skill(state)
    confidence = float(state.get("intent_confidence", 0.0) or 0.0)
    return confidence >= SHORT_PATH_CONFIDENCE and skill is not None


def should_task_plan(state: PipelineState | dict) -> bool:
    """先 resolve 再判定；调用方应把 skill 写回 state['short_path_skill']。"""
    return not short_path_predicate(state)
