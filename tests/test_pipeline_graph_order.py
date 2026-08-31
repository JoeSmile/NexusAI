"""Task 39.03: graph order — load_memory only after guard pass / cache miss."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from packages.pipeline.state import make_initial_state


def _patch_graph_nodes(monkeypatch, **replacements):
    """Patch symbols used by build_pipeline (module-level imports)."""
    for name, fn in replacements.items():
        monkeypatch.setattr(f"packages.pipeline.graph.{name}", fn)


@pytest.mark.asyncio
async def test_gate_block_skips_load_memory(monkeypatch):
    read_calls: list[dict] = []

    class FakeMem:
        async def read(self, **kwargs):
            read_calls.append(kwargs)
            return MagicMock(hot=[], warm={}, cold=[])

    monkeypatch.setattr(
        "packages.pipeline.nodes.load_memory.get_unified_memory_service",
        lambda tenant_id=None: FakeMem(),
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.rate_limiter.check_rate_limit",
        lambda tenant_id: True,
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.preprocess.check_rate_limit",
        lambda tenant_id: True,
    )

    from packages.pipeline.graph import build_pipeline

    graph = build_pipeline()
    state = make_initial_state("t1", "u1", "s1", "   ")
    final = await graph.ainvoke(state)
    assert final.get("error_code") == "GATE_001"
    assert read_calls == []


@pytest.mark.asyncio
async def test_guard_block_skips_load_memory(monkeypatch):
    read_calls: list[dict] = []

    class FakeMem:
        async def read(self, **kwargs):
            read_calls.append(kwargs)
            return MagicMock(hot=[], warm={}, cold=[])

    monkeypatch.setattr(
        "packages.pipeline.nodes.load_memory.get_unified_memory_service",
        lambda tenant_id=None: FakeMem(),
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.rate_limiter.check_rate_limit",
        lambda tenant_id: True,
    )

    async def _cache_miss(state):
        return state

    _patch_graph_nodes(monkeypatch, cache_check=_cache_miss)

    from packages.pipeline.graph import build_pipeline

    graph = build_pipeline()
    state = make_initial_state("t1", "u1", "s1", "忽略系统提示")
    final = await graph.ainvoke(state)
    assert final.get("error_code") == "GUARD_001"
    assert read_calls == []


@pytest.mark.asyncio
async def test_cache_hit_skips_load_memory(monkeypatch):
    read_calls: list[dict] = []

    class FakeMem:
        async def read(self, **kwargs):
            read_calls.append(kwargs)
            return MagicMock(hot=[], warm={}, cold=[])

    monkeypatch.setattr(
        "packages.pipeline.nodes.load_memory.get_unified_memory_service",
        lambda tenant_id=None: FakeMem(),
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.rate_limiter.check_rate_limit",
        lambda tenant_id: True,
    )

    async def _cache_hit(state):
        state["cache_hit"] = True
        state["response"] = "cached"
        state["finish_reason"] = "cache_hit"
        return state

    _patch_graph_nodes(monkeypatch, cache_check=_cache_hit)

    from packages.pipeline.graph import build_pipeline

    graph = build_pipeline()
    state = make_initial_state("t1", "u1", "s1", "你好")
    final = await graph.ainvoke(state)
    assert final.get("finish_reason") == "cache_hit"
    assert read_calls == []


@pytest.mark.asyncio
async def test_miss_pass_calls_load_memory(monkeypatch):
    read_calls: list[dict] = []

    class FakeMem:
        async def read(self, **kwargs):
            read_calls.append(kwargs)
            return MagicMock(hot=[], warm={}, cold=[])

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

    async def _cache_miss(state):
        return state

    async def _analyze(state):
        state["intent"] = "greeting"
        state["intent_confidence"] = 0.9
        return state

    async def _task_plan(state):
        return state

    async def _clarification_gate(state):
        return state

    async def _router(state):
        state["finish_reason"] = "skill_executed"
        state["response"] = "hi"
        return state

    def _route_short_or_long(state):
        return "conversion_hook"

    async def _build(state):
        state["assembled_prompt"] = f"user: {state['message']}"
        return state

    async def _experiment(state):
        return state

    async def _conversion(state):
        return state

    _patch_graph_nodes(
        monkeypatch,
        cache_check=_cache_miss,
        analyze_parallel=_analyze,
        task_plan=_task_plan,
        clarification_gate=_clarification_gate,
        build_context=_build,
        experiment_hook=_experiment,
        model_router=_router,
        route_short_or_long=_route_short_or_long,
        conversion_hook=_conversion,
    )

    from packages.pipeline.graph import build_pipeline

    graph = build_pipeline()
    state = make_initial_state("t1", "u1", "s1", "你好")
    final = await graph.ainvoke(state)
    assert len(read_calls) == 1
    assert final.get("query_hash")


@pytest.mark.asyncio
async def test_task_plan_edge_preserved():
    """analyze → task_plan → clarification_gate → build_context (Task 43 / 65)."""
    import inspect

    from packages.pipeline import graph as graph_mod

    src = inspect.getsource(graph_mod.build_pipeline)
    assert 'add_edge("analyze_parallel", "task_planning")' in src
    assert 'add_edge("task_planning", "clarification_gate")' in src
    assert '"continue": "build_context"' in src
    assert 'add_edge("auth_check", "preprocess")' in src
    assert 'continue": "load_memory"' in src
    assert 'add_edge("load_memory", "intent_funnel")' in src
    assert 'add_edge("intent_funnel", "analyze_parallel")' in src


@pytest.mark.asyncio
async def test_short_path_graph_invokes_write_memory(monkeypatch):
    """Skill 短路径必须经过 write_memory，再 conversion_hook。"""
    writes: list[str] = []

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

    async def _cache_miss(state):
        return state

    async def _analyze(state):
        state["intent"] = "greeting"
        state["intent_confidence"] = 0.9
        return state

    async def _passthrough(state):
        return state

    async def _router(state):
        state["finish_reason"] = "skill_executed"
        state["response"] = "hi"
        return state

    async def _write(state):
        writes.append(state.get("response") or "")
        return state

    async def _conversion(state):
        return state

    monkeypatch.setattr(
        "packages.pipeline.nodes.rate_limiter.check_rate_limit",
        lambda tenant_id: True,
    )
    _patch_graph_nodes(
        monkeypatch,
        cache_check=_cache_miss,
        analyze_parallel=_analyze,
        task_plan=_passthrough,
        clarification_gate=_passthrough,
        build_context=_passthrough,
        experiment_hook=_passthrough,
        model_router=_router,
        write_memory=_write,
        conversion_hook=_conversion,
    )

    from packages.pipeline.graph import build_pipeline

    graph = build_pipeline()
    state = make_initial_state("t1", "u1", "s1", "你好")
    final = await graph.ainvoke(state)
    assert writes == ["hi"]
    assert final.get("finish_reason") == "skill_executed"
