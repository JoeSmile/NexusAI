"""Task 65 slice 7 — coreference table."""

from __future__ import annotations

import json

import pytest

from packages.plan.coref import (
    apply_coref_to_plan,
    apply_coref_to_text,
    infer_coref_table,
    invalidate_coref_if_drift,
    load_session_coref,
    merge_coref_tables,
    save_session_coref,
    warm_coref_key,
)
from packages.plan.models import CorefEntry, CorefTable
from packages.pipeline.state import make_initial_state


def test_apply_coref_replaces_pronoun():
    table = CorefTable(
        entries=[
            CorefEntry(
                entity_id="e1",
                canonical="汇丰银行",
                mentions=["它"],
                resolved_value="汇丰银行",
                confidence=0.95,
            )
        ]
    )
    assert apply_coref_to_text("它的收益率怎么样", table) == "汇丰银行的收益率怎么样"


def test_infer_coref_from_entities():
    table = infer_coref_table("它的收益怎么样", {"org": "汇丰银行"})
    assert len(table.entries) == 1
    assert table.entries[0].canonical == "汇丰银行"


def test_apply_coref_to_plan_steps():
    table = CorefTable(
        entries=[
            CorefEntry(
                entity_id="e1",
                canonical="汇丰银行",
                mentions=["它"],
                resolved_value="汇丰银行",
                confidence=0.9,
            )
        ]
    )
    plan = {
        "goal": "查它的理财",
        "query_rewrite": {
            "rewritten_query": "它的理财",
            "sub_queries": ["它的收益率"],
        },
        "steps": [
            {
                "id": "s1",
                "capability_id": "rag.ask",
                "sub_query": "它的产品",
                "params": {"query": "它"},
            }
        ],
    }
    out = apply_coref_to_plan(plan, table)
    assert "汇丰银行" in out["goal"]
    assert "汇丰银行" in out["query_rewrite"]["rewritten_query"]
    assert "汇丰银行" in out["steps"][0]["sub_query"]
    assert out["steps"][0]["params"]["query"] == "汇丰银行"


def test_merge_coref_tables_dedupes_by_id():
    session = CorefTable(
        entries=[
            CorefEntry(
                entity_id="e1",
                canonical="A",
                mentions=["它"],
                resolved_value="A",
                confidence=0.5,
            )
        ]
    )
    fresh = CorefTable(
        entries=[
            CorefEntry(
                entity_id="e1",
                canonical="B",
                mentions=["它", "这家"],
                resolved_value="B",
                confidence=0.9,
            ),
            CorefEntry(
                entity_id="e2",
                canonical="C",
                mentions=["那个"],
                resolved_value="C",
                confidence=0.8,
            ),
        ]
    )
    merged = merge_coref_tables(session, fresh)
    assert len(merged.entries) == 2
    assert merged.entries[0].resolved_value == "B"


def test_load_session_coref_from_warm():
    state = make_initial_state("t1", "u1", "s1", "q")
    key = warm_coref_key("s1")
    table = CorefTable(
        entries=[
            CorefEntry(
                entity_id="e1",
                canonical="X",
                mentions=["它"],
                resolved_value="X",
                confidence=1.0,
            )
        ]
    )
    state["warm_memory"] = {key: json.dumps(table.model_dump(mode="json"))}
    loaded = load_session_coref(state)
    assert loaded.entries[0].canonical == "X"


@pytest.mark.asyncio
async def test_invalidate_coref_on_drift(monkeypatch):
    cleared: list[str] = []

    async def _clear(state):
        cleared.append("yes")
        return None

    monkeypatch.setattr("packages.plan.coref.clear_session_coref", _clear)
    state = make_initial_state("t1", "u1", "s1", "不是那个，算了")
    assert await invalidate_coref_if_drift(state) is True
    assert cleared == ["yes"]


@pytest.mark.asyncio
async def test_save_session_coref_writes_warm(monkeypatch):
    writes: list[dict] = []

    async def _write(self, tier, *, user_id, **payload):
        writes.append({"tier": tier, "user_id": user_id, **payload})
        return {"tier": tier}

    monkeypatch.setattr(
        "packages.memory.memory_service.UnifiedMemoryService.write",
        _write,
    )
    monkeypatch.setattr(
        "packages.database.vector_ops.delete_user_memory",
        lambda *a, **k: True,
    )
    state = make_initial_state("t1", "u1", "s1", "q")
    table = CorefTable(
        entries=[
            CorefEntry(
                entity_id="e1",
                canonical="Y",
                mentions=["它"],
                resolved_value="Y",
                confidence=0.8,
            )
        ]
    )
    await save_session_coref(state, table)
    assert warm_coref_key("s1") in state["warm_memory"]
    assert writes and writes[0]["source"] == "coref"
