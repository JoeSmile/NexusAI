"""Task 89 M1 — hot 折叠为 message history 别名；prompt 轮次锁定。"""

from __future__ import annotations

from packages.memory.memory_service import MemoryBundle, UnifiedMemoryService


def test_hot_is_message_history_alias() -> None:
    turns = [{"role": "user", "content": "帮我写口播"}]
    bundle = MemoryBundle(hot=turns, warm={}, cold=[])
    assert bundle.message_history is bundle.hot
    assert bundle.message_history == turns


def test_assemble_recent_turns_section_bytes_locked() -> None:
    """M1 不得改注入轮次的原文与小节标题（路线图 golden）。"""
    bundle = MemoryBundle(
        hot=[
            {"role": "user", "content": "帮我写口播"},
            {"role": "assistant", "content": "好"},
        ],
        warm={},
        cold=[],
    )
    text = UnifiedMemoryService().assemble_prompt_block(
        bundle, context_window_tokens=8000, budget_ratio=1.0
    )
    assert "[最近对话]\nuser: 帮我写口播\nassistant: 好" in text
