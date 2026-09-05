"""S3 — A/B exposure flushed once in conversion_hook."""

from __future__ import annotations

import pytest

from packages.pipeline.nodes.conversion_hook import conversion_hook
from packages.pipeline.nodes.experiment_hook import experiment_hook
from packages.pipeline.state import make_initial_state


@pytest.mark.asyncio
async def test_non_stream_exposure_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "packages.pipeline.nodes.experiment_hook.assign_variant",
        lambda _uid: {"experiment_id": "e1", "variant": "A", "variant_config": {}},
    )
    monkeypatch.setattr(
        "packages.pipeline.nodes.conversion_hook.record_event",
        lambda **kw: calls.append(str(kw.get("event_type"))),
    )
    state = make_initial_state("t", "u", "s", "hi")
    await experiment_hook(state)
    assert state.get("pending_exposure")
    state["response"] = "ok"
    await conversion_hook(state)
    assert calls.count("exposure") == 1
    assert calls.count("conversion") == 1
    assert state.get("pending_exposure") is None


@pytest.mark.asyncio
async def test_stream_without_write_memory_still_exposes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "packages.pipeline.nodes.conversion_hook.record_event",
        lambda **kw: calls.append(str(kw.get("event_type"))),
    )
    state = make_initial_state("t", "u", "s", "hi")
    state["pending_exposure"] = {"experiment_id": "e1", "variant": "B"}
    state["ab_experiment_id"] = "e1"
    state["ab_variant"] = "B"
    state["stream_mode"] = True
    state["finish_reason"] = "routed_to_llm"
    state["response"] = ""
    await conversion_hook(state)
    assert calls == ["exposure"]


@pytest.mark.asyncio
async def test_hold_path_no_exposure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "packages.pipeline.nodes.conversion_hook.record_event",
        lambda **kw: calls.append(str(kw.get("event_type"))),
    )
    state = make_initial_state("t", "u", "s", "hi")
    state["finish_reason"] = "clarification_pending"
    state["response"] = "请补充"
    await conversion_hook(state)
    assert calls == []


@pytest.mark.asyncio
async def test_empty_pending_no_exposure_on_build_context_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "packages.pipeline.nodes.conversion_hook.record_event",
        lambda **kw: calls.append(str(kw.get("event_type"))),
    )
    state = make_initial_state("t", "u", "s", "hi")
    # build_context raised → conversion_hook never ran; simulate arriving without pending
    await conversion_hook(state)
    assert calls == []
