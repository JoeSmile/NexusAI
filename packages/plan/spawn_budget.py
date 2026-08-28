"""F4 Spawn 预算 — 并行 fan-out 硬闸（Task 56 切片 3）。"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SpawnBudget:
    """单次编排 run 的 spawn 上限。"""

    max_workers: int
    max_depth: int
    max_spawn_total: int

    def can_spawn(self, *, depth: int, spawned_total: int) -> bool:
        """depth = 本批并行宽度；spawned_total = 已累计 spawn 次数。"""
        if depth > self.max_workers:
            return False
        if depth > self.max_depth:
            return False
        return spawned_total + depth <= self.max_spawn_total


def _env_int(name: str, default: int, *, lo: int, hi: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return max(lo, min(hi, int(raw)))
    except ValueError:
        return default


def resolve_spawn_budget() -> SpawnBudget:
    """从环境变量解析预算（有界夹紧）。"""
    workers = _env_int("ORCHESTRATOR_MAX_WORKERS", 8, lo=1, hi=32)
    depth = _env_int("ORCHESTRATOR_MAX_DEPTH", 3, lo=1, hi=16)
    total = _env_int("ORCHESTRATOR_MAX_SPAWN_TOTAL", 32, lo=4, hi=256)
    total = max(total, workers)
    return SpawnBudget(max_workers=workers, max_depth=depth, max_spawn_total=total)
