"""S4 案 A — 记忆进本轮 user，system 不残留背景。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from packages.memory.memory_service import MEMORY_ISOLATION_HEADER
from packages.pipeline.context_messages import (
    UNTRUSTED_ATTACHMENT_NOTICE,
    build_llm_messages,
)
from packages.pipeline.state import make_initial_state
from packages.prompt_service import DEFAULT_CHAT_SYSTEM

GOLDEN = Path("data/context/golden/s4_case_a.jsonl")


def test_bg_goes_to_final_user_not_system() -> None:
    state = make_initial_state("t1", "u1", "s1", "帮我写口播")
    state["memory_prompt_block"] = MEMORY_ISOLATION_HEADER + "\n[用户背景]\n- pref:style: 短视频"
    state["user_prompt_prefix"] = "PREFIX"
    state["hot_memory"] = [
        {"role": "user", "content": "上一轮"},
        {"role": "assistant", "content": "好的"},
    ]
    msgs = build_llm_messages(state, system_template=DEFAULT_CHAT_SYSTEM)
    assert msgs[0]["role"] == "system"
    assert "短视频" not in msgs[0]["content"]
    assert MEMORY_ISOLATION_HEADER not in msgs[0]["content"]
    assert UNTRUSTED_ATTACHMENT_NOTICE in msgs[0]["content"]
    assert msgs[-1]["role"] == "user"
    assert "短视频" in msgs[-1]["content"]
    assert "PREFIX" in msgs[-1]["content"]
    assert msgs[-1]["content"].endswith("帮我写口播")
    assert msgs[1]["content"] == "上一轮"


def test_no_memory_user_is_just_query() -> None:
    state = make_initial_state("t1", "u1", "s1", "你好")
    msgs = build_llm_messages(state, system_template="你是助手。")
    assert msgs[-1]["content"] == "你好"
    assert MEMORY_ISOLATION_HEADER not in msgs[0]["content"]


def test_golden_file_has_at_least_30() -> None:
    if not GOLDEN.is_file():
        pytest.skip("s4 golden missing")
    rows = [
        json.loads(line)
        for line in GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) >= 30


def test_golden_structural_shape() -> None:
    if not GOLDEN.is_file():
        pytest.skip("s4 golden missing")
    rows = [
        json.loads(line)
        for line in GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for row in rows:
        state = make_initial_state("t1", "u1", "s1", str(row["message"]))
        state["memory_prompt_block"] = str(row.get("memory_prompt_block") or "")
        state["user_prompt_prefix"] = str(row.get("user_prompt_prefix") or "")
        state["hot_memory"] = list(row.get("hot") or [])
        msgs = build_llm_messages(state, system_template=DEFAULT_CHAT_SYSTEM)
        sys_c = msgs[0]["content"]
        user_c = msgs[-1]["content"]
        expect = row.get("expect") or {}
        if expect.get("bg_not_in_system"):
            bg = str(row.get("bg_needle") or "")
            if bg:
                assert bg not in sys_c, row["id"]
        if expect.get("bg_in_user"):
            bg = str(row.get("bg_needle") or "")
            if bg:
                assert bg in user_c, row["id"]
        if expect.get("query_in_user"):
            assert str(row["message"]) in user_c, row["id"]
        assert MEMORY_ISOLATION_HEADER not in sys_c, row["id"]
        assert UNTRUSTED_ATTACHMENT_NOTICE in sys_c, row["id"]


def test_trim_keeps_background_on_last_user() -> None:
    state = make_initial_state("t1", "u1", "s1", "本轮问题")
    state["memory_prompt_block"] = MEMORY_ISOLATION_HEADER + "\nNEEDLE-BG-KEEP"
    state["hot_memory"] = [
        {"role": "user", "content": ("old " * 400) + str(i)}
        for i in range(12)
    ]
    msgs = build_llm_messages(state, system_template="助手")
    assert msgs[-1]["role"] == "user"
    assert "NEEDLE-BG-KEEP" in msgs[-1]["content"]
    assert msgs[-1]["content"].endswith("本轮问题")


@pytest.mark.asyncio
async def test_per_item_drift_keeps_clean_warm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("packages.redis_tools.get_sync_redis", lambda **_k: None)
    from packages.guardrails.memory_drift import MEMORY_BG_OMITTED_NOTICE
    from packages.pipeline.nodes.build_context import build_context

    state = make_initial_state("t1", "u1", "s1", "写口播")
    state["warm_memory"] = {
        "identity:name": "小明",
        "note": "家人们快来直播间",
    }
    out = await build_context(state)
    block = out.get("memory_prompt_block") or ""
    assert "小明" in block
    assert "家人们" not in block
    assert MEMORY_BG_OMITTED_NOTICE in block
    assert MEMORY_ISOLATION_HEADER not in build_llm_messages(
        out, system_template="助手"
    )[0]["content"]


@pytest.mark.asyncio
async def test_cold_drift_warns_does_not_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("packages.redis_tools.get_sync_redis", lambda **_k: None)
    from packages.pipeline.nodes.build_context import build_context

    state = make_initial_state("t1", "u1", "s1", "上次说了啥")
    state["cold_memory"] = [{"id": "c1", "summary": "家人们昨天聊过课表"}]
    out = await build_context(state)
    assert "家人们" in (out.get("memory_prompt_block") or "")


def test_drift_audit_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("packages.redis_tools.get_sync_redis", lambda **_k: None)
    from packages.guardrails.memory_drift import should_audit_drift_key

    assert should_audit_drift_key("t-cd", "u-cd", "note") is True
    assert should_audit_drift_key("t-cd", "u-cd", "note") is False
    assert should_audit_drift_key("t-cd", "u-cd", "other") is True


@pytest.mark.skipif(
    os.getenv("RUN_S4_GOLDEN_LAB") != "1",
    reason="S4 LLM lab gate (背景≥90%/漂移0/营销越界0); set RUN_S4_GOLDEN_LAB=1",
)
def test_golden_lab_llm_gate() -> None:
    pytest.skip("lab runner compares live model; not wired in unit tests")
