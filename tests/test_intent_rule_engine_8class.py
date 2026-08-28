"""Task 65 slice 8 — 8-class rule engine + short path binding."""

from __future__ import annotations

import pytest

from packages.intent.core.rule_engine import RuleBasedIntentEngine
from packages.intent.models.intent_models import IntentType
from packages.pipeline.intent_path import (
    SHORT_PATH_INTENTS,
    resolve_short_path_skill,
    short_path_predicate,
)
from packages.pipeline.state import make_initial_state
from packages.skills.registry import registry


@pytest.fixture(scope="module", autouse=True)
def _discover_skills():
    registry.discover()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("你好", IntentType.GREETING),
        ("介绍一下产品", IntentType.PRE_SALES),
        ("和竞品对比一下", IntentType.PRE_SALES),
        ("怎么退款", IntentType.AFTER_SALES),
        ("我要投诉", IntentType.AFTER_SALES),
        ("写个口播脚本", IntentType.CONTENT_CREATION),
        ("分析一下这个热点", IntentType.CONTENT_ANALYSIS),
        ("报销流程是什么", IntentType.KNOWLEDGE_QUERY),
        ("提醒我明天开会", IntentType.FUNCTION),
    ],
)
def test_rule_engine_business_intents(text: str, expected: IntentType):
    result = RuleBasedIntentEngine().detect_intent(text)
    assert result is not None
    assert result.intent == expected
    assert result.confidence >= 0.8


def test_short_path_after_sales_refund():
    state = make_initial_state("t", "u", "s", "怎么退款")
    state["intent"] = "after_sales"
    state["intent_confidence"] = 0.9
    assert "after_sales" in SHORT_PATH_INTENTS
    skill = resolve_short_path_skill(state)
    assert skill is not None
    assert skill.id == "refund_policy"
    assert short_path_predicate(state) is True


def test_short_path_after_sales_complaint():
    state = make_initial_state("t", "u", "s", "我要投诉升级")
    state["intent"] = "after_sales"
    state["intent_confidence"] = 0.9
    skill = resolve_short_path_skill(state)
    assert skill is not None
    assert skill.id == "complaint_escalation"


def test_pre_sales_not_short_path():
    state = make_initial_state("t", "u", "s", "报个价")
    state["intent"] = "pre_sales"
    state["intent_confidence"] = 0.95
    assert resolve_short_path_skill(state) is None
    assert short_path_predicate(state) is False


def test_content_creation_not_short_path():
    state = make_initial_state("t", "u", "s", "写口播")
    state["intent"] = "content_creation"
    state["intent_confidence"] = 0.95
    assert resolve_short_path_skill(state) is None
