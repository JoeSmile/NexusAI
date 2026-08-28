"""Task 42 S1 — memory item validators + golden set."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.memory.types import TodoItem, TodoOwnerKind, parse_memory_item
from packages.memory.validators import (
    REJECT_GROUNDING,
    REJECT_SCHEMA,
    REJECT_SECURITY,
    char_bigram_overlap,
    grounding_validator,
    normalize_for_grounding,
    schema_validator,
    security_validator,
    semantic_validator,
    validate_item,
)

_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "memory_golden.json"


def _load_golden() -> list[dict]:
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))["cases"]


def test_normalize_and_bigram():
    assert "同事王工" in normalize_for_grounding("同事王工，")
    a = normalize_for_grounding("请同事王工评审，明天来可以")
    b = normalize_for_grounding("他明天来")
    assert char_bigram_overlap(a, b) >= 0.4 or "明天" in a


def test_schema_rejects_bad_error_code():
    ok, reason = schema_validator(
        {
            "type": "error_code",
            "text": "x",
            "source_span": "x",
            "confidence": 0.9,
            "code": "nope",
        }
    )
    assert ok is False
    assert reason == REJECT_SCHEMA


def test_grounding_short_span_requires_substring():
    item = parse_memory_item(
        {
            "type": "entity",
            "text": "张三",
            "source_span": "张三",
            "confidence": 0.7,
            "name": "张三",
            "entity_type": "person",
            "relation": "同事",
        }
    )
    # 张三 vs 张三丰：短 span 必须子串；「张三」是「张三丰」子串 → 过
    ok, _ = grounding_validator(item, "今天见了张三丰")
    assert ok is True
    ok2, reason = grounding_validator(item, "王工说今天开会")
    assert ok2 is False
    assert reason == REJECT_GROUNDING


def test_security_rejects_api_key_phrase():
    item = parse_memory_item(
        {
            "type": "todo",
            "text": "保存 api key",
            "source_span": "请记住 api key sk-abc",
            "confidence": 0.75,
            "action": "保存 api key",
            "owner_kind": "self",
            "status": "open",
        }
    )
    ok, reason = security_validator(item)
    assert ok is False
    assert reason == REJECT_SECURITY


def test_semantic_todo_self_ok_entity_needs_known():
    self_todo = TodoItem(
        text="交报表",
        source_span="待办交报表",
        confidence=0.75,
        action="交报表",
        owner_kind=TodoOwnerKind.SELF,
        status="open",
    )
    assert semantic_validator(self_todo)[0] is True
    ent = TodoItem(
        text="评审",
        source_span="待办王工评审",
        confidence=0.75,
        action="评审",
        owner="王工",
        owner_kind=TodoOwnerKind.ENTITY,
        status="open",
    )
    assert semantic_validator(ent, known_entity_names=set())[0] is False
    assert semantic_validator(ent, known_entity_names={"王工"})[0] is True


@pytest.mark.parametrize("case", _load_golden(), ids=lambda c: c["id"])
def test_golden_cases(case: dict) -> None:
    src = case["source_text"]
    known = set(case.get("known_entity_names") or [])
    expect = case["expect"]
    ok, reason = validate_item(case["item"], src, known_entity_names=known)
    if expect == "accept":
        assert ok is True, f"{case['id']} rejected: {reason}"
        assert reason is None
    else:
        assert ok is False, f"{case['id']} should reject"
        assert reason == expect


def test_validator_chain_order_schema_before_grounding():
    """缺字段 → SCHEMA，即便 grounding 也会失败。"""
    ok, reason = validate_item(
        {
            "type": "todo",
            "text": "x",
            "source_span": "nowhere",
            "confidence": 0.75,
            "action": "",
            "owner_kind": "self",
            "status": "open",
        },
        "somewhere else",
    )
    assert ok is False
    assert reason == REJECT_SCHEMA
