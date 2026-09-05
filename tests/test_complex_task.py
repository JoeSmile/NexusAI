"""Task 88 A1 — conservative complex-task gate (docs/complex-task-visibility.md)."""

from __future__ import annotations

import pytest

from packages.pipeline.complex_task import is_complex_task
from packages.pipeline.nodes.task_plan import should_async_plan_on_stream
from packages.pipeline.state import make_initial_state

SIMPLE: list[tuple[str, str, float]] = [
    ("你好", "greeting", 0.95),
    ("谢谢", "conversation", 0.9),
    ("再见", "conversation", 0.9),
    ("哈哈", "conversation", 0.85),
    ("在吗", "greeting", 0.9),
    ("早上好", "greeting", 0.92),
    ("嗯嗯", "conversation", 0.85),
    ("你是谁", "greeting", 0.9),
    ("拜拜", "conversation", 0.88),
    ("聊聊", "conversation", 0.8),
]

COMPLEX: list[tuple[str, str, float]] = [
    ("帮我写个口播稿", "content_creation", 0.8),
    ("帮我写周报", "content_creation", 0.75),
    ("分析一下竞品", "content_analysis", 0.8),
    ("热点挖掘考研", "content_analysis", 0.7),
    ("报销流程是什么", "knowledge_query", 0.85),
    ("对比小红书和抖音投放", "content_analysis", 0.6),
    ("帮我分析这条内容爆不爆", "content_analysis", 0.7),
    ("公司管理制度怎么查", "knowledge_query", 0.8),
    ("生成一篇小红书文案", "content_creation", 0.8),
    ("提醒我明天下午开会", "function", 0.8),
]


def _state(text: str, intent: str, conf: float, *, stream: bool = True):
    st = make_initial_state("t", "u", "s", text)
    st["stream_mode"] = stream
    st["intent"] = intent
    st["intent_confidence"] = conf
    return st


@pytest.mark.parametrize("text,intent,conf", SIMPLE)
def test_simple_queries_are_not_complex(text: str, intent: str, conf: float) -> None:
    assert is_complex_task(_state(text, intent, conf)) is False


@pytest.mark.parametrize("text,intent,conf", COMPLEX)
def test_complex_queries_are_complex(text: str, intent: str, conf: float) -> None:
    assert is_complex_task(_state(text, intent, conf)) is True


def test_unsure_conversation_stays_deterministic() -> None:
    """拿不准归确定性路径：闲聊长句也不规划。"""
    st = _state("今天心情一般就随便聊聊吧", "conversation", 0.55)
    assert is_complex_task(st) is False


def test_short_path_greeting_never_complex() -> None:
    from packages.skills.registry import registry

    registry.discover()
    st = _state("你好", "greeting", 0.95)
    assert is_complex_task(st) is False


def test_async_plan_on_by_default_for_complex_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ASYNC_TASK_PLAN_ON_STREAM", raising=False)
    monkeypatch.delenv("FORCE_TASK_PLAN_ON_STREAM", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_ENABLED", raising=False)
    st = _state("帮我写个口播稿", "content_creation", 0.8)
    assert should_async_plan_on_stream(st) is True


def test_complex_does_not_plan_when_orchestrator_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ASYNC_TASK_PLAN_ON_STREAM", raising=False)
    monkeypatch.setenv("ORCHESTRATOR_ENABLED", "false")
    st = _state("帮我写个口播稿", "content_creation", 0.8)
    assert should_async_plan_on_stream(st) is False


def test_async_plan_still_off_for_simple_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ASYNC_TASK_PLAN_ON_STREAM", raising=False)
    monkeypatch.delenv("FORCE_TASK_PLAN_ON_STREAM", raising=False)
    st = _state("谢谢", "conversation", 0.9)
    assert should_async_plan_on_stream(st) is False
