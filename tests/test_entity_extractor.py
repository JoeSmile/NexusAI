"""L0 rule-based entity extraction (Phase 1 MVP)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from packages.intent.core.entity_extractor import extract_entities, map_agent_type_slots
from backend.pipeline.cache.fingerprint_cache import make_fingerprint
from backend.pipeline.nodes.analyze_parallel import analyze_parallel
from backend.pipeline.state import make_initial_state


@pytest.mark.parametrize(
    ("message", "intent", "expected"),
    [
        (
            "订单号 ABC123456 要退款，质量问题",
            "after_sales",
            {
                "order_id": "ABC123456",
                "reason": "质量问题",
                "issue_type": "退款",
            },
        ),
        (
            "专业版来 3 套，报个价",
            "pre_sales",
            {
                "sku": "专业版",
                "quantity": "3",
                "product_scope": "专业版",
            },
        ),
        (
            "帮我写关于新能源车销量的口播脚本",
            "content_creation",
            {"topic": "新能源车销量"},
        ),
        (
            "查一下报销流程",
            "knowledge_query",
            {"object": "报销"},
        ),
        (
            "明天下午提醒我开会",
            "function",
            {"time": "明天", "action": "提醒"},
        ),
        ("你好", "greeting", {}),
        ("", "after_sales", {}),
    ],
)
def test_extract_entities(message: str, intent: str, expected: dict[str, str]) -> None:
    assert extract_entities(message, intent) == expected


def test_map_agent_type_slots_copies_refund_reason() -> None:
    entities = {"issue_type": "退款"}
    out = map_agent_type_slots("after_sales", entities)
    assert out["reason"] == "退款"


def test_fingerprint_differs_when_entities_differ() -> None:
    fp_a = make_fingerprint("after_sales", {"order_id": "ABC111111"})
    fp_b = make_fingerprint("after_sales", {"order_id": "ABC222222"})
    assert fp_a != fp_b


@pytest.mark.asyncio
async def test_analyze_parallel_populates_entities(monkeypatch) -> None:
    def fake_detect(self, text: str):
        result = MagicMock()
        result.intent = MagicMock(value="after_sales")
        result.confidence = 0.9
        result.source = "rule"
        result.tier = None
        return result

    monkeypatch.setattr(
        "packages.intent.core.intent_classifier.IntentClassifier.detect_intent",
        fake_detect,
    )
    msg = "订单号 ABC123456 要退款，质量问题"
    state = make_initial_state("t1", "u1", "s1", msg)
    out = await analyze_parallel(state)
    assert out["entities"]["order_id"] == "ABC123456"
    assert out["entities"]["reason"] == "质量问题"
    assert out["entities"]["issue_type"] == "退款"
    assert out["fingerprint"] == make_fingerprint("after_sales", out["entities"])
