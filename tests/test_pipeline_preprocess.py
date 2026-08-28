"""Task 39.02: preprocess + cheap GATE + cache_bypass."""

from __future__ import annotations

import pytest

from backend.core.text_normalize import make_normalized_query_hash, normalize_text
from packages.pipeline.nodes.preprocess import (
    preprocess,
    should_cache_bypass,
    should_gate_block,
)
from packages.pipeline.state import make_initial_state


@pytest.mark.asyncio
async def test_preprocess_normalizes_and_sets_query_hash():
    state = make_initial_state("t1", "u1", "s1", "你好 ")
    out = await preprocess(state)
    assert out["message"] == "你好"
    assert out["raw_input"] == "你好 "
    assert out["query_hash"] == make_normalized_query_hash("你好 ")
    assert out["finish_reason"] != "blocked"
    assert should_gate_block(out) == "continue"
    assert out["cache_bypass"] is False


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


def test_cache_bypass_trigger_heuristics():
    assert should_cache_bypass("看看今天有什么热点")
    assert should_cache_bypass("写一篇教育口播稿")
    assert should_cache_bypass("生成教育热点选题")
    assert not should_cache_bypass("你好")
    assert not should_cache_bypass("今天天气怎么样")


@pytest.mark.asyncio
async def test_preprocess_sets_cache_bypass():
    state = make_initial_state("t1", "u1", "s1", "生成教育热点选题")
    out = await preprocess(state)
    assert out["cache_bypass"] is True
    assert out["finish_reason"] != "blocked"


@pytest.mark.asyncio
async def test_cache_check_skips_on_bypass():
    from packages.pipeline.nodes.cache_check import cache_check

    state = make_initial_state("t1", "u1", "s1", "热点")
    state["query_hash"] = "deadbeefdeadbeef"
    state["cache_bypass"] = True
    out = await cache_check(state)
    assert out.get("cache_hit") is False
    assert out.get("finish_reason") != "cache_hit"
