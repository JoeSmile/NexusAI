"""Task 42 S2 — structured extraction + pending bind."""

from __future__ import annotations

import asyncio
import json

from backend.core.memory.item_rules import (
    context_overlap_ok,
    extract_structured_items,
    pending_key,
    pending_value,
    pick_latest_pending,
    pronoun_hits,
    should_bind_pending,
)
from backend.core.memory.validators import validate_item


def test_extract_entity_decision_todo_error():
    text = "请同事王工评审；决定采用 Redis；待办:周五前提交报表；失败 AUTH_001"
    cands = extract_structured_items(text)
    types = {c.item.type for c in cands}
    assert "entity" in types
    assert "decision" in types
    assert "todo" in types
    assert "error_code" in types
    # R7 order
    idxs = [c.item.type for c in cands]
    assert idxs.index("entity") < idxs.index("todo")


def test_pronoun_and_pending_key():
    assert pronoun_hits("他明天来") == ["他"]
    assert pending_key("sess-1", "他").startswith("pending:sess-1:")


def test_bind_r11_positive():
    sid = "s1"
    pk = pending_key(sid, "他")
    payload = json.loads(
        pending_value(
            antecedent="他",
            context_snippet="他明天来",
            user_turn_at_create=1,
        )
    )
    assert should_bind_pending(
        session_id=sid,
        pending_key_str=pk,
        pending_payload=payload,
        explicit_name="王工",
        explicit_turn="请同事王工评审，明天来可以",
        current_user_turns=2,
    )
    assert context_overlap_ok("请同事王工评审，明天来可以", "他明天来")


def test_bind_r11_no_overlap():
    sid = "s1"
    pk = pending_key(sid, "他")
    payload = json.loads(
        pending_value(
            antecedent="他",
            context_snippet="他明天来",
            user_turn_at_create=1,
        )
    )
    assert not should_bind_pending(
        session_id=sid,
        pending_key_str=pk,
        pending_payload=payload,
        explicit_name="李四",
        explicit_turn="今天天气不错顺便提下同事李四",
        current_user_turns=5,
    )


def test_pick_latest_pending():
    a = ("pending:s:他", {"last_mention_ts": "2026-01-01T00:00:00+00:00"})
    b = ("pending:s:她", {"last_mention_ts": "2026-01-02T00:00:00+00:00"})
    assert pick_latest_pending([a, b])[0] == "pending:s:她"


def test_validate_extracted_entity():
    text = "请同事王工明天来"
    cands = extract_structured_items(text)
    ent = next(c for c in cands if c.item.type == "entity")
    ok, reason = validate_item(ent.item, text, known_entity_names=set())
    assert ok is True, reason


def test_chatty_bare_mention_no_entity():
    """R4: 闲聊裸提不抽 entity。"""
    cands = extract_structured_items("我同事也遇到过")
    assert not any(c.item.type == "entity" for c in cands)


def test_async_extract_smoke():
    async def _run():
        from backend.core.memory.extractor import RuleExtractor

        ex = RuleExtractor()
        return await ex.extract(user_message="请记住项目代号星火")

    out = asyncio.run(_run())
    assert out
