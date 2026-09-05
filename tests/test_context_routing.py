"""S3 — workflow/skill skip build_context."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from packages.pipeline.state import make_initial_state


def _patch_graph_nodes(monkeypatch, **replacements):
    for name, fn in replacements.items():
        monkeypatch.setattr(f"packages.pipeline.graph.{name}", fn)


def _stub_common(monkeypatch) -> None:
    class FakeMem:
        async def read(self, **kwargs):
            return MagicMock(hot=[], warm={}, cold=[], warm_meta={})

        def assemble_prompt_block(self, bundle, query=""):
            return ""

    monkeypatch.setattr(
        "packages.pipeline.nodes.load_memory.get_unified_memory_service",
        lambda tenant_id=None: FakeMem(),
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.build_context.get_unified_memory_service",
        lambda tenant_id=None: FakeMem(),
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.rate_limiter.check_rate_limit",
        lambda tenant_id: True,
    )


@pytest.mark.asyncio
async def test_workflow_path_build_context_not_called(monkeypatch: pytest.MonkeyPatch) -> None:
    bc = {"n": 0}

    async def _cache_miss(state):
        return state

    async def _passthrough(state):
        return state

    async def _task(state):
        state["finish_reason"] = "workflow_triggered"
        state["triggered_run"] = {"id": "run1"}
        state["response"] = "wf"
        return state

    async def _bc(state):
        bc["n"] += 1
        return state

    async def _write(state):
        return state

    _stub_common(monkeypatch)
    _patch_graph_nodes(
        monkeypatch,
        cache_check=_cache_miss,
        analyze_parallel=_passthrough,
        task_plan=_task,
        clarification_gate=_passthrough,
        experiment_hook=_passthrough,
        context_gate=_passthrough,
        build_context=_bc,
        write_memory=_write,
        conversion_hook=_passthrough,
    )
    from packages.pipeline.graph import build_pipeline

    graph = build_pipeline()
    final = await graph.ainvoke(make_initial_state("t1", "u1", "s1", "跑流程"))
    assert bc["n"] == 0
    assert final.get("finish_reason") == "workflow_triggered"


@pytest.mark.asyncio
async def test_skill_path_build_context_not_called(monkeypatch: pytest.MonkeyPatch) -> None:
    bc = {"n": 0}

    async def _cache_miss(state):
        return state

    async def _passthrough(state):
        return state

    async def _analyze(state):
        state["intent"] = "greeting"
        state["intent_confidence"] = 0.9
        return state

    async def _gate(state):
        state["session_attachment_present"] = False
        return state

    async def _skill(state):
        state["finish_reason"] = "skill_executed"
        state["response"] = "hi"
        return state

    async def _bc(state):
        bc["n"] += 1
        return state

    _stub_common(monkeypatch)
    monkeypatch.setattr(
        "packages.pipeline.nodes.context_gate.should_take_skill_short_path",
        lambda state, **_k: True,
    )
    _patch_graph_nodes(
        monkeypatch,
        cache_check=_cache_miss,
        analyze_parallel=_analyze,
        task_plan=_passthrough,
        clarification_gate=_passthrough,
        experiment_hook=_passthrough,
        context_gate=_gate,
        run_skill=_skill,
        build_context=_bc,
        write_memory=_passthrough,
        conversion_hook=_passthrough,
    )
    from packages.pipeline.graph import build_pipeline

    graph = build_pipeline()
    final = await graph.ainvoke(make_initial_state("t1", "u1", "s1", "你好"))
    assert bc["n"] == 0
    assert final.get("finish_reason") == "skill_executed"


@pytest.mark.asyncio
async def test_long_path_still_hits_build_context(monkeypatch: pytest.MonkeyPatch) -> None:
    bc = {"n": 0}

    async def _cache_miss(state):
        return state

    async def _passthrough(state):
        return state

    async def _analyze(state):
        state["intent"] = "knowledge_query"
        state["intent_confidence"] = 0.4
        return state

    async def _gate(state):
        state["session_attachment_present"] = False
        return state

    async def _bc(state):
        bc["n"] += 1
        return state

    async def _router(state):
        state["finish_reason"] = "routed_to_llm"
        state["response"] = "ans"
        return state

    _stub_common(monkeypatch)
    _patch_graph_nodes(
        monkeypatch,
        cache_check=_cache_miss,
        analyze_parallel=_analyze,
        task_plan=_passthrough,
        clarification_gate=_passthrough,
        experiment_hook=_passthrough,
        context_gate=_gate,
        build_context=_bc,
        model_router=_router,
        llm_generate=_passthrough,
        guardrails_output=_passthrough,
        write_memory=_passthrough,
        conversion_hook=_passthrough,
        route_short_or_long=lambda _s: "llm_generate",
    )
    from packages.pipeline.graph import build_pipeline

    graph = build_pipeline()
    final = await graph.ainvoke(make_initial_state("t1", "u1", "s1", "解释一下"))
    assert bc["n"] == 1
    assert final.get("finish_reason") == "routed_to_llm"
