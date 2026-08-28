"""Task 56 切片 3 — SpawnBudget + 执行分组 + params 引用。"""

from __future__ import annotations

from packages.plan.execution import group_independent_batches
from packages.plan.params_resolve import resolve_step_params
from packages.plan.spawn_budget import SpawnBudget


def test_spawn_budget_can_spawn_within_limits() -> None:
    b = SpawnBudget(max_workers=4, max_depth=3, max_spawn_total=10)
    assert b.can_spawn(depth=2, spawned_total=5)
    assert not b.can_spawn(depth=5, spawned_total=0)
    assert not b.can_spawn(depth=2, spawned_total=9)


def test_group_independent_batches_levels() -> None:
    steps = [
        {"id": "s1", "depends_on": []},
        {"id": "s2", "depends_on": []},
        {"id": "s3", "depends_on": ["s1", "s2"]},
    ]
    batches = group_independent_batches(steps)
    assert len(batches) == 2
    assert {s["id"] for s in batches[0]} == {"s1", "s2"}
    assert batches[1][0]["id"] == "s3"


def test_resolve_step_params_source_step() -> None:
    results = {"s1": {"output": "prior text"}}
    out = resolve_step_params({"source_step": "s1", "extra": 1}, results)
    assert out["message"] == "prior text"
    assert out["extra"] == 1
