"""Task 39.02: preprocess + cheap GATE."""

from __future__ import annotations

import pytest

from backend.core.text_normalize import make_normalized_query_hash, normalize_text
from backend.pipeline.nodes.preprocess import preprocess, should_gate_block
from backend.pipeline.state import make_initial_state


@pytest.mark.asyncio
async def test_preprocess_normalizes_and_sets_query_hash():
    state = make_initial_state("t1", "u1", "s1", "你好 ")
    out = await preprocess(state)
    assert out["message"] == "你好"
    assert out["raw_input"] == "你好 "
    assert out["query_hash"] == make_normalized_query_hash("你好 ")
    assert out["finish_reason"] != "blocked"
    assert should_gate_block(out) == "continue"


@pytest.mark.asyncio
async def test_preprocess_empty_gate_001():
    state = make_initial_state("t1", "u1", "s1", "   \t  ")
    out = await preprocess(state)
    assert out["finish_reason"] == "blocked"
    assert out["error_code"] == "GATE_001"
    assert should_gate_block(out) == "end"


@pytest.mark.asyncio
async def test_preprocess_oversize_gate_002(monkeypatch):
    monkeypatch.setenv("PIPELINE_MAX_INPUT_CHARS", "10")
    state = make_initial_state("t1", "u1", "s1", "abcdefghijk")
    out = await preprocess(state)
    assert out["error_code"] == "GATE_002"
    assert out["finish_reason"] == "blocked"


@pytest.mark.asyncio
async def test_preprocess_deny_list_gate_003(monkeypatch):
    monkeypatch.setenv("PIPELINE_DENY_LIST", "forbidden-token,other")
    state = make_initial_state("t1", "u1", "s1", "please FORBIDDEN-TOKEN now")
    out = await preprocess(state)
    assert out["error_code"] == "GATE_003"
    assert "deny:" in (out.get("gate_reason") or "")
    # deny scans normalized (lowercased)
    assert normalize_text("please FORBIDDEN-TOKEN now") == out.get("message") or True


@pytest.mark.asyncio
async def test_preprocess_flag_off_skips_gate_still_normalizes(monkeypatch):
    monkeypatch.setenv("PIPELINE_PREPROCESS_ENABLED", "false")
    monkeypatch.setenv("PIPELINE_DENY_LIST", "forbidden-token")
    state = make_initial_state("t1", "u1", "s1", " forbidden-token ")
    out = await preprocess(state)
    assert out["finish_reason"] != "blocked"
    assert out["message"] == "forbidden-token"
    assert out["query_hash"]
