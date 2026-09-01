"""Task 77.2 — sparse topic funnel L1/L2 with rule fallback."""

from __future__ import annotations

import json
import time

import pytest

from packages.intent.belief_store import get_belief, set_belief
from packages.pipeline.followup_lexicon import (
    is_followup_utterance,
    is_topic_switch_utterance,
)
from packages.pipeline.nodes.intent_funnel import (
    parse_l2_json,
    run_funnel,
    should_run_l2,
)
from packages.pipeline.nodes.model_router import model_router
from packages.pipeline.state import make_initial_state
from packages.plan.clarification import session_has_pending_clarification, warm_pending_key


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.data[key] = value
        return True

    def delete(self, key: str) -> int:
        return 1 if self.data.pop(key, None) is not None else 0


@pytest.fixture
def belief_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(
        "packages.intent.belief_store.get_sync_redis",
        lambda **_k: fake,
    )
    return fake


def test_topic_switch_lexicon_not_followup() -> None:
    assert is_topic_switch_utterance("另外问")
    assert is_topic_switch_utterance("另外问报销")
    assert is_topic_switch_utterance("换个话题")
    assert is_topic_switch_utterance("新问题")
    assert not is_followup_utterance("另外问")
    assert is_followup_utterance("那个呢")
    assert not is_topic_switch_utterance("那个呢")


def test_should_run_l2_sparse_only(belief_redis: _FakeRedis) -> None:
    idle = make_initial_state("t1", "u1", "s1", "今天天气怎么样")
    assert should_run_l2(idle, belief=None, hint_new_topic=False) is False

    follow = make_initial_state("t1", "u1", "s1", "那个呢")
    assert should_run_l2(follow, belief=None, hint_new_topic=False) is True

    switch = make_initial_state("t1", "u1", "s1", "另外问报销")
    assert should_run_l2(switch, belief=None, hint_new_topic=True) is True

    set_belief("t1", "u1", "s1", {"status": "ACTIVE", "slots": {}, "summary": "订票"})
    active = make_initial_state("t1", "u1", "s1", "改到后天")
    assert should_run_l2(active, belief={"status": "ACTIVE"}, hint_new_topic=False) is True


def test_parse_l2_json_valid_and_garbage() -> None:
    ok = parse_l2_json(
        '{"is_new_topic": false, "continue_prev_task": true, '
        '"updated_slots": {}, "confidence": 0.8, "reason": "user_supplied_followup"}'
    )
    assert ok is not None
    assert ok["continue_prev_task"] is True
    assert parse_l2_json("not json") is None
    assert parse_l2_json('{"is_new_topic": true}') is None


@pytest.mark.asyncio
async def test_no_belief_does_not_call_llm(belief_redis: _FakeRedis) -> None:
    called = {"n": 0}

    async def llm(**_k) -> str:
        called["n"] += 1
        return "{}"

    state = make_initial_state("t1", "u1", "s1", "那个呢")
    out = await run_funnel(state, llm_call=llm)
    assert called["n"] == 0
    assert out["is_new_topic"] is True


@pytest.mark.asyncio
async def test_valid_json_continue_and_bad_json_falls_to_rules(
    belief_redis: _FakeRedis,
) -> None:
    set_belief("t1", "u1", "s1", {"status": "ACTIVE", "slots": {}, "summary": "订票"})

    async def good(**_k) -> str:
        return (
            '{"is_new_topic": false, "continue_prev_task": true, '
            '"updated_slots": {"date": "明天"}, "confidence": 0.9, "reason": "x"}'
        )

    out = await run_funnel(
        make_initial_state("t1", "u1", "s1", "那个呢"), llm_call=good
    )
    assert out["is_new_topic"] is False
    assert out["continue_prev_task"] is True
    assert out["funnel_block_short_path"] is True

    async def bad(**_k) -> str:
        return "<<<not-json>>>"

    out2 = await run_funnel(
        make_initial_state("t1", "u1", "s1", "那个呢"), llm_call=bad
    )
    assert out2["continue_prev_task"] is True
    assert out2["is_new_topic"] is False


@pytest.mark.asyncio
async def test_topic_switch_is_new_and_hello_allows_greeting(
    belief_redis: _FakeRedis,
) -> None:
    set_belief("t1", "u1", "s1", {"status": "ACTIVE", "slots": {}, "summary": "订票"})
    switch = await run_funnel(make_initial_state("t1", "u1", "s1", "另外问报销"))
    assert switch["is_new_topic"] is True
    assert switch["continue_prev_task"] is False
    assert switch["funnel_block_short_path"] is False

    hello = await run_funnel(make_initial_state("t1", "u1", "s9", "你好"))
    assert hello["funnel_block_short_path"] is False
    assert hello["is_new_topic"] is True


@pytest.mark.asyncio
async def test_is_new_topic_does_not_unload_session_attachments(
    belief_redis: _FakeRedis,
) -> None:
    from datetime import UTC, datetime, timedelta

    from packages.attachments.inject import inject_session_attachments
    from packages.attachments.parse import AttachmentBlock
    from packages.attachments.store import MemoryAttachmentStore, set_attachment_store

    store = MemoryAttachmentStore()
    store.save(
        tenant_id="t1",
        session_id="s1",
        uploaded_by="u1",
        name="合同.pdf",
        media_type="application/pdf",
        size=100,
        status="ready",
        storage_path="/tmp/c.pdf",
        expired_at=datetime.now(UTC) + timedelta(days=7),
        blocks=[
            AttachmentBlock(
                block_index=0,
                kind="page",
                text="合同第12条 违约责任",
                char_count=12,
                page=1,
            )
        ],
        attachment_id="a1",
    )
    set_attachment_store(store)
    try:
        set_belief("t1", "u1", "s1", {"status": "ACTIVE", "slots": {}, "summary": "订票"})
        switch = await run_funnel(make_initial_state("t1", "u1", "s1", "另外问报销"))
        assert switch["is_new_topic"] is True
        assert get_belief("t1", "u1", "s1") is None
        state = make_initial_state("t1", "u1", "s1", "违约条款呢")
        await inject_session_attachments(state)
        blob = state.get("memory_prompt_block") or ""
        assert state.get("file_blocks")
        assert "违约" in blob
    finally:
        set_attachment_store(None)


@pytest.mark.asyncio
async def test_pending_clarification_skips_l2(belief_redis: _FakeRedis) -> None:
    set_belief("t1", "u1", "s1", {"status": "ACTIVE", "slots": {}, "summary": "订票"})
    state = make_initial_state("t1", "u1", "s1", "好的")
    state["warm_memory"] = {
        warm_pending_key("s1"): json.dumps(
            {
                "source": "missing_entities",
                "question": "哪家银行？",
                "options": ["汇丰"],
                "created_at": time.time(),
                "original_query": "查流水",
            }
        )
    }
    assert session_has_pending_clarification(state) is True
    called = {"n": 0}

    async def llm(**_k) -> str:
        called["n"] += 1
        return '{"is_new_topic": true, "continue_prev_task": false, "updated_slots": {}, "confidence": 1, "reason": "x"}'

    out = await run_funnel(state, llm_call=llm)
    assert called["n"] == 0
    assert out.get("funnel_skipped") == "clarification_pending"
    assert out.get("is_new_topic") is not True


@pytest.mark.asyncio
async def test_model_router_blocks_greeting_short_path_when_funnel_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = make_initial_state("t1", "u1", "s1", "嗯", preferred_model="deepseek-v4-flash")
    state["intent"] = "greeting"
    state["intent_confidence"] = 0.99
    state["funnel_block_short_path"] = True
    called = {"n": 0}

    class _Skill:
        id = "greet"

    monkeypatch.setattr(
        "packages.pipeline.nodes.model_router.resolve_short_path_skill",
        lambda _s: _Skill(),
    )

    async def _boom(**k):
        called["n"] += 1
        raise AssertionError("must not execute greeting skill")

    monkeypatch.setattr(
        "packages.pipeline.nodes.model_router.registry.execute_skill",
        _boom,
    )
    out = await model_router(state)
    assert called["n"] == 0
    assert out.get("finish_reason") != "skill_executed"
