"""S3 — skill gate four-tuple vs router file_blocks."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from packages.pipeline.short_path import should_take_skill_short_path
from packages.pipeline.state import make_initial_state


@pytest.fixture(autouse=True)
def _fake_skill(monkeypatch: pytest.MonkeyPatch) -> None:
    skill = MagicMock()
    skill.id = "greeting"
    monkeypatch.setattr(
        "packages.pipeline.short_path.resolve_short_path_skill",
        lambda _s: skill,
    )


def _skill_state(**extra):
    state = make_initial_state("t1", "u1", "s1", "你好")
    state["intent"] = "greeting"
    state["intent_confidence"] = 0.9
    state.update(extra)
    return state


def test_gate_ready_without_attachments() -> None:
    assert should_take_skill_short_path(_skill_state(), attachments_present=False) is True


def test_gate_blocks_when_attachments_present() -> None:
    assert should_take_skill_short_path(_skill_state(), attachments_present=True) is False


def test_router_file_blocks_block_short_path() -> None:
    state = _skill_state(file_blocks=[{"text": "条款"}])
    assert should_take_skill_short_path(state) is False


def test_funnel_block_is_not_skill() -> None:
    state = _skill_state(funnel_block_short_path=True)
    assert should_take_skill_short_path(state, attachments_present=False) is False


def test_low_confidence_is_not_skill() -> None:
    state = _skill_state()
    state["intent_confidence"] = 0.5
    assert should_take_skill_short_path(state, attachments_present=False) is False


def test_missing_skill_is_not_short_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "packages.pipeline.short_path.resolve_short_path_skill",
        lambda _s: None,
    )
    assert should_take_skill_short_path(_skill_state(), attachments_present=False) is False
