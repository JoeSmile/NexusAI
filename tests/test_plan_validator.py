"""Task 56 切片 2 — PlanIR 验证器 + 工具检索 + query 重写。"""

from __future__ import annotations

import pytest

from backend.core.plan.tool_index import search_capabilities
from backend.core.plan.validator import PlanValidationError, validate_plan_ir
from packages.pipeline.nodes.query_rewrite import attach_query_rewrite_to_plan


def _caps() -> dict[str, dict]:
    return {
        "hotspot.dig": {"param_spec": {}},
        "script.gen": {"param_spec": {}},
    }


def _valid_plan(**overrides) -> dict:
    base = {
        "goal": "dig and script",
        "version": 1,
        "max_depth": 3,
        "query_rewrite": {
            "rewritten_query": "挖掘热点并写稿",
            "sub_queries": [],
            "language": "zh",
            "clarification_needed": False,
        },
        "steps": [
            {
                "id": "s1",
                "capability_id": "hotspot.dig",
                "params": {},
                "depends_on": [],
                "mode": "serial",
                "on_fail": "fail",
            },
            {
                "id": "s2",
                "capability_id": "script.gen",
                "params": {},
                "depends_on": ["s1"],
                "mode": "serial",
                "on_fail": "fail",
            },
        ],
    }
    base.update(overrides)
    return base


def test_validate_rejects_unknown_capability() -> None:
    plan = _valid_plan()
    plan["steps"][0]["capability_id"] = "evil.tool"
    with pytest.raises(PlanValidationError, match="whitelist"):
        validate_plan_ir(plan, caps_by_id=_caps())


def test_validate_rejects_cycle() -> None:
    plan = _valid_plan()
    plan["steps"] = [
        {
            "id": "s1",
            "capability_id": "hotspot.dig",
            "params": {},
            "depends_on": ["s2"],
            "mode": "serial",
            "on_fail": "fail",
        },
        {
            "id": "s2",
            "capability_id": "script.gen",
            "params": {},
            "depends_on": ["s1"],
            "mode": "serial",
            "on_fail": "fail",
        },
    ]
    with pytest.raises(PlanValidationError, match="cycle"):
        validate_plan_ir(plan, caps_by_id=_caps())


def test_validate_rejects_depth_exceeded() -> None:
    plan = _valid_plan()
    plan["steps"] = [
        {
            "id": "s1",
            "capability_id": "hotspot.dig",
            "params": {},
            "depends_on": [],
            "mode": "serial",
            "on_fail": "fail",
        },
        {
            "id": "s2",
            "capability_id": "script.gen",
            "params": {},
            "depends_on": ["s1"],
            "mode": "serial",
            "on_fail": "fail",
        },
        {
            "id": "s3",
            "capability_id": "hotspot.dig",
            "params": {},
            "depends_on": ["s2"],
            "mode": "serial",
            "on_fail": "fail",
        },
        {
            "id": "s4",
            "capability_id": "script.gen",
            "params": {},
            "depends_on": ["s3"],
            "mode": "serial",
            "on_fail": "fail",
        },
    ]
    with pytest.raises(PlanValidationError, match="depth"):
        validate_plan_ir(plan, caps_by_id=_caps())


def test_validate_accepts_valid_dag() -> None:
    ir = validate_plan_ir(_valid_plan(), caps_by_id=_caps())
    assert ir.steps[0].id == "s1"
    assert ir.query_rewrite is not None


def test_tool_index_top_k() -> None:
    caps = [
        {"id": "hotspot.dig", "name": "热点挖掘", "description": "热点"},
        {"id": "script.gen", "name": "口播", "description": "脚本"},
        {"id": "style.extract", "name": "风格", "description": "风格提取"},
    ]
    many = caps + [
        {"id": f"cap.{i}", "name": f"other{i}", "description": "misc"}
        for i in range(12)
    ]
    out = search_capabilities(many, "hotspot.dig script", top_k=2)
    assert len(out) == 2
    assert {c["id"] for c in out} == {"hotspot.dig", "script.gen"}


def test_tool_index_top_k_limit_when_no_match() -> None:
    many = [
        {"id": f"cap.{i}", "name": f"other{i}", "description": "misc"}
        for i in range(15)
    ]
    out = search_capabilities(many, "zzz", top_k=3)
    assert len(out) == 3


def test_tool_index_small_catalog_full_expose() -> None:
    caps = [{"id": "a", "name": "A", "description": ""}]
    assert search_capabilities(caps, "x") == caps


def test_attach_query_rewrite_fallback() -> None:
    out = attach_query_rewrite_to_plan(
        {"steps": [{"capability_id": "hotspot.dig", "params": {}}]},
        original_message="原始问题",
    )
    assert out["query_rewrite"]["rewritten_query"] == "原始问题"
    assert out["goal"]
