"""Task 71 slice 1 — rule_engine acceptance (Checklist B1–B10)."""

from __future__ import annotations

import pytest

from packages.intent.core.rule_engine import RuleBasedIntentEngine
from packages.intent.models.intent_models import IntentType

# Checklist B1–B8 + extras (各意图 ≥3 句)
_RULE_CASES: list[tuple[str, IntentType]] = [
    # greeting
    ("你好", IntentType.GREETING),
    ("您好", IntentType.GREETING),
    ("早上好", IntentType.GREETING),
    # pre_sales
    ("你们产品多少钱", IntentType.PRE_SALES),
    ("介绍一下产品", IntentType.PRE_SALES),
    ("和竞品对比一下", IntentType.PRE_SALES),
    # after_sales
    ("发票怎么开", IntentType.AFTER_SALES),
    ("怎么退款", IntentType.AFTER_SALES),
    ("我要投诉", IntentType.AFTER_SALES),
    # content_creation
    ("帮我写周报", IntentType.CONTENT_CREATION),
    ("写个口播脚本", IntentType.CONTENT_CREATION),
    ("生成一篇文案", IntentType.CONTENT_CREATION),
    # content_analysis
    ("分析下这个热点", IntentType.CONTENT_ANALYSIS),
    ("分析一下这个热点", IntentType.CONTENT_ANALYSIS),
    ("评估一下选题", IntentType.CONTENT_ANALYSIS),
    # knowledge_query
    ("报销流程是什么", IntentType.KNOWLEDGE_QUERY),
    ("请假制度是什么", IntentType.KNOWLEDGE_QUERY),
    ("管理制度在哪", IntentType.KNOWLEDGE_QUERY),
    # function
    ("提醒我明天开会", IntentType.FUNCTION),
    ("帮我记个事，明天上午开会", IntentType.FUNCTION),
    ("设置闹钟", IntentType.FUNCTION),
    # greeting（身份问句走问候短路径，禁止丢给 LLM）
    ("你是谁", IntentType.GREETING),
    # conversation（问模型归属仍走会话，避免「模型」误伤售前）
    ("你使用的是什么模型", IntentType.CONVERSATION),
    ("你们用的什么模型", IntentType.CONVERSATION),
]


@pytest.mark.parametrize(("text", "expected"), _RULE_CASES)
def test_rule_engine_eight_class_hits(text: str, expected: IntentType) -> None:
    result = RuleBasedIntentEngine().detect_intent(text)
    assert result is not None, f"no rule hit for {text!r}"
    assert result.intent == expected
    assert result.confidence >= 0.8


def test_model_identity_is_conversation_not_presales() -> None:
    """08-25：问模型归属 → conversation；单字『模型』不误伤售前。"""
    eng = RuleBasedIntentEngine()
    hit = eng.detect_intent("你使用的是什么模型")
    assert hit is not None
    assert hit.intent == IntentType.CONVERSATION

    price = eng.detect_intent("你们大模型平台多少钱")
    assert price is not None
    assert price.intent == IntentType.PRE_SALES


def test_compound_greeting_does_not_short_circuit_creation() -> None:
    """B10：你好 + 写文章 → content_creation，短路径不得截胡。"""
    hit = RuleBasedIntentEngine().detect_intent("你好，帮我写个文章")
    assert hit is not None
    assert hit.intent == IntentType.CONTENT_CREATION
