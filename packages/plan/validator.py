"""PlanIR 验证器（Task 56）— 白名单 / 环检测 / 深度与 params 上限。"""

from __future__ import annotations

import json
from collections import deque
from typing import Any

from packages.plan.models import PlanIR, normalize_plan_dict
from packages.workflow.ir import _FORBIDDEN_PARAM_KEYS, validate_params_against_spec

MAX_STEPS = 32
MAX_DEPTH = 3
MAX_PARAMS_BYTES = 4096


class PlanValidationError(ValueError):
    """计划未通过验证器。"""


def topological_sort_steps(steps: list[dict[str, Any]]) -> list[str]:
    """Kahn 拓扑排序；成环抛 PlanValidationError。"""
    ids = [str(s["id"]) for s in steps]
    id_set = set(ids)
    if len(id_set) != len(ids):
        raise PlanValidationError("duplicate step id")
    indeg: dict[str, int] = {i: 0 for i in ids}
    adj: dict[str, list[str]] = {i: [] for i in ids}
    for step in steps:
        sid = str(step["id"])
        for dep in step.get("depends_on") or []:
            dep_s = str(dep)
            if dep_s not in id_set:
                raise PlanValidationError(f"unknown dependency: {dep_s}")
            adj[dep_s].append(sid)
            indeg[sid] += 1
    q: deque[str] = deque([i for i in ids if indeg[i] == 0])
    order: list[str] = []
    while q:
        n = q.popleft()
        order.append(n)
        for nxt in adj[n]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    if len(order) != len(ids):
        raise PlanValidationError("cycle detected in depends_on")
    return order


def _dag_depth(steps: list[dict[str, Any]]) -> int:
    """最长依赖链深度（节点数）。"""
    by_id = {str(s["id"]): s for s in steps}
    memo: dict[str, int] = {}

    def depth(sid: str, visiting: set[str]) -> int:
        if sid in memo:
            return memo[sid]
        if sid in visiting:
            raise PlanValidationError("cycle detected in depends_on")
        visiting.add(sid)
        deps = by_id[sid].get("depends_on") or []
        if not deps:
            memo[sid] = 1
        else:
            memo[sid] = 1 + max(depth(str(d), visiting) for d in deps)
        visiting.discard(sid)
        return memo[sid]

    return max(depth(str(s["id"]), set()) for s in steps)


def validate_plan_ir(
    plan: dict[str, Any],
    *,
    caps_by_id: dict[str, dict[str, Any]],
    fallback_goal: str = "",
) -> PlanIR:
    """硬校验：白名单 capability、环、深度、params 体积、param_spec。"""
    if not caps_by_id:
        raise PlanValidationError("empty capability whitelist")

    normalized = normalize_plan_dict(plan, fallback_goal=fallback_goal)
    steps = normalized.get("steps") or []
    if not steps:
        raise PlanValidationError("task_plan.steps must be a non-empty list")
    if len(steps) > MAX_STEPS:
        raise PlanValidationError(f"too many steps (max {MAX_STEPS})")

    allowed = set(caps_by_id.keys())
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise PlanValidationError(f"step[{i}] must be object")
        cap_id = step.get("capability_id")
        if not isinstance(cap_id, str) or not cap_id.strip():
            raise PlanValidationError(f"step[{i}] missing capability_id")
        if cap_id not in allowed:
            raise PlanValidationError(f"capability not in whitelist: {cap_id}")
        params = step.get("params") or {}
        if not isinstance(params, dict):
            raise PlanValidationError(f"step[{i}] params must be object")
        bad = set(params) & _FORBIDDEN_PARAM_KEYS
        if bad:
            raise PlanValidationError(f"step[{i}] forbidden keys: {sorted(bad)}")
        blob = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
        if len(blob.encode("utf-8")) > MAX_PARAMS_BYTES:
            raise PlanValidationError(f"step[{i}] params exceed {MAX_PARAMS_BYTES} bytes")
        meta = caps_by_id[cap_id]
        validate_params_against_spec(params, meta.get("param_spec") or {})

    topological_sort_steps(steps)
    depth = _dag_depth(steps)
    max_depth = int(normalized.get("max_depth") or MAX_DEPTH)
    if depth > MAX_DEPTH:
        raise PlanValidationError(f"plan depth {depth} exceeds max {MAX_DEPTH}")
    if depth > max_depth:
        raise PlanValidationError(f"plan depth {depth} exceeds declared max_depth {max_depth}")

    return PlanIR.model_validate(normalized)
