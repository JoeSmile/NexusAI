"""A/B pipeline hooks（Task 23.03）"""

from __future__ import annotations

import pytest

from backend.pipeline.nodes.conversion_hook import conversion_hook
from backend.pipeline.nodes.experiment_hook import experiment_hook
from backend.pipeline.state import make_initial_state


@pytest.mark.asyncio
async def test_experiment_hook_assigns_and_records_exposure(monkeypatch):
    calls: list[dict] = []

    monkeypatch.setattr(
        "backend.pipeline.nodes.experiment_hook.assign_variant",
        lambda user_id: {
            "experiment_id": "exp1",
            "variant": "B",
            "variant_config": {"prompt_prefix": "PREFIX"},
        },
    )

    def _record(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        "backend.pipeline.nodes.experiment_hook.record_event", _record
    )

    state = make_initial_state("acme", "u1", "s1", "hello")
    out = await experiment_hook(state)
    assert out["ab_experiment_id"] == "exp1"
    assert out["ab_variant"] == "B"
    assert out["raw_input"].startswith("PREFIX")
    assert len(calls) == 1
    assert calls[0]["event_type"] == "exposure"
    assert calls[0]["group"] == "B"


@pytest.mark.asyncio
async def test_experiment_hook_no_assignment(monkeypatch):
    monkeypatch.setattr(
        "backend.pipeline.nodes.experiment_hook.assign_variant",
        lambda user_id: None,
    )
    state = make_initial_state("acme", "u1", "s1", "hello")
    out = await experiment_hook(state)
    assert out.get("ab_experiment_id") is None


@pytest.mark.asyncio
async def test_conversion_hook_skips_without_experiment():
    state = make_initial_state("acme", "u1", "s1", "hello")
    state["response"] = "ok"
    out = await conversion_hook(state)
    assert out["response"] == "ok"


@pytest.mark.asyncio
async def test_conversion_hook_skips_without_response(monkeypatch):
    called = {"n": 0}

    def _record(**kwargs):
        called["n"] += 1

    monkeypatch.setattr(
        "backend.pipeline.nodes.conversion_hook.record_event", _record
    )
    state = make_initial_state("acme", "u1", "s1", "hello")
    state["ab_experiment_id"] = "exp1"
    state["ab_variant"] = "A"
    state["response"] = ""
    await conversion_hook(state)
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_conversion_hook_records(monkeypatch):
    calls: list[dict] = []

    monkeypatch.setattr(
        "backend.pipeline.nodes.conversion_hook.record_event",
        lambda **kwargs: calls.append(kwargs),
    )
    state = make_initial_state("acme", "u1", "s1", "hello")
    state["ab_experiment_id"] = "exp1"
    state["ab_variant"] = "A"
    state["response"] = "done"
    await conversion_hook(state)
    assert len(calls) == 1
    assert calls[0]["event_type"] == "conversion"


@pytest.mark.asyncio
async def test_conversion_hook_swallows_db_errors(monkeypatch):
    def _boom(**kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "backend.pipeline.nodes.conversion_hook.record_event", _boom
    )
    state = make_initial_state("acme", "u1", "s1", "hello")
    state["ab_experiment_id"] = "exp1"
    state["ab_variant"] = "A"
    state["response"] = "done"
    out = await conversion_hook(state)
    assert out["response"] == "done"
