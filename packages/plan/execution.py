"""PlanIR 执行序分组（Task 56 切片 3）。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def step_levels(steps: list[dict[str, Any]]) -> dict[str, int]:
    """按 depends_on 计算拓扑层级（根 = 0）。"""
    by_id = {str(s["id"]): s for s in steps}
    memo: dict[str, int] = {}

    def level(sid: str, visiting: set[str]) -> int:
        if sid in memo:
            return memo[sid]
        if sid in visiting:
            raise ValueError("cycle detected in depends_on")
        visiting.add(sid)
        deps = by_id[sid].get("depends_on") or []
        if not deps:
            memo[sid] = 0
        else:
            memo[sid] = 1 + max(level(str(d), visiting) for d in deps)
        visiting.discard(sid)
        return memo[sid]

    for sid in by_id:
        level(sid, set())
    return memo


def group_independent_batches(steps: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """同层步骤可并行；层间按拓扑序串行。"""
    if not steps:
        return []
    levels = step_levels(steps)
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for step in steps:
        buckets[levels[str(step["id"])]].append(step)
    return [buckets[k] for k in sorted(buckets)]
