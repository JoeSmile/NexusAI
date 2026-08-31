"""Task 78.4 — slash commands after auth, before preprocess."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from packages.intent.belief_store import get_belief, set_belief
from packages.memory.context_summarize import l1_warm_key
from packages.pipeline.nodes.command_gate import (
    HELP_TEXT,
    command_gate,
    parse_slash_command,
    route_after_command,
)
from packages.pipeline.state import make_initial_state


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


@pytest.fixture(autouse=True)
def _quiet_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("packages.audit.write_audit_sync", lambda *_a, **_k: True)


@pytest.fixture
def belief_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(
        "packages.intent.belief_store.get_sync_redis",
        lambda **_k: fake,
    )
    return fake


def test_parse_known_and_unknown() -> None:
    assert parse_slash_command("hello") is None
    assert parse_slash_command("/reset") == ("reset", "")
    assert parse_slash_command("/feedback 卡片看不清") == ("feedback", "卡片看不清")
    assert parse_slash_command("/foo") == ("foo", "")
    assert parse_slash_command("/forget") == ("forget", "")


@pytest.mark.asyncio
async def test_help_and_unknown_do_not_hit_llm() -> None:
    state = make_initial_state("t1", "u1", "s1", "/help")
    out = await command_gate(state)
    assert out["finish_reason"] == "command_result"
    assert HELP_TEXT in (out.get("response") or "")
    assert out.get("cache_hit") is not True
    assert route_after_command(out) == "end"

    unknown = await command_gate(make_initial_state("t1", "u1", "s1", "/foo"))
    assert unknown["finish_reason"] == "command_result"
    assert HELP_TEXT in (unknown.get("response") or "")
    assert route_after_command(unknown) == "end"


@pytest.mark.asyncio
async def test_reset_drops_l1_keeps_belief(belief_redis: _FakeRedis) -> None:
    set_belief(
        "t1",
        "u1",
        "s1",
        {"status": "ACTIVE", "slots": {"bank": "汇丰"}, "summary": "查流水"},
    )
    with patch(
        "packages.pipeline.nodes.command_gate.session_hard_reset",
        return_value={"archived": 4, "l1_dropped": True},
    ) as reset, patch(
        "packages.intent.belief_store.delete_belief"
    ) as del_belief:
        out = await command_gate(make_initial_state("t1", "u1", "s1", "/reset"))
    reset.assert_called_once_with("t1", "u1", "s1")
    del_belief.assert_not_called()
    assert out["finish_reason"] == "command_result"
    got = get_belief("t1", "u1", "s1")
    assert got is not None
    assert got["status"] == "ACTIVE"
    assert got["slots"]["bank"] == "汇丰"


@pytest.mark.asyncio
async def test_new_clears_belief(belief_redis: _FakeRedis) -> None:
    set_belief("t1", "u1", "s1", {"status": "ACTIVE", "slots": {}, "summary": "订票"})
    with patch(
        "packages.pipeline.nodes.command_gate.session_hard_reset",
        return_value={"archived": 1, "l1_dropped": True},
    ):
        out = await command_gate(make_initial_state("t1", "u1", "s1", "/new"))
    assert get_belief("t1", "u1", "s1") is None
    assert out["finish_reason"] == "command_result"
    assert route_after_command(out) == "end"


@pytest.mark.asyncio
async def test_context_has_counts_no_secrets() -> None:
    bundle = MagicMock()
    bundle.hot = [{"content": "a"}, {"content": "b"}]
    bundle.warm = {l1_warm_key("s1"): '{"summary":"x"}'}

    class _Mem:
        async def read(self, **_k):
            return bundle

    with patch(
        "packages.pipeline.nodes.command_gate.get_unified_memory_service",
        lambda **_k: _Mem(),
    ), patch(
        "packages.pipeline.nodes.command_gate.get_belief",
        return_value={"status": "ACTIVE", "slots": {"secret": "do-not-leak"}},
    ):
        out = await command_gate(make_initial_state("t1", "u1", "s1", "/context"))
    text = out.get("response") or ""
    assert "2" in text
    assert "ACTIVE" in text
    assert "摘要" in text
    assert "secret" not in text
    assert "do-not-leak" not in text


@pytest.mark.asyncio
async def test_feedback_truncates_and_uses_other() -> None:
    saved: dict = {}

    class _DB:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def save_feedback(self, **kwargs):
            saved.update(kwargs)
            return MagicMock(id=1)

    with patch(
        "packages.database.DatabaseManager",
        _DB,
    ):
        out = await command_gate(
            make_initial_state("t1", "u1", "s1", "/feedback " + ("好" * 80))
        )
    assert out["finish_reason"] == "command_result"
    assert saved.get("feedback_type") == "other"
    comment = str(saved.get("comment") or "")
    assert len(comment) <= 200
    assert "好" in comment


@pytest.mark.asyncio
async def test_plain_text_continues() -> None:
    state = make_initial_state("t1", "u1", "s1", "查汇丰流水")
    out = await command_gate(state)
    assert route_after_command(out) == "continue"
    assert out.get("finish_reason") != "command_result"


@pytest.mark.asyncio
async def test_help_skips_load_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    read_calls: list[dict] = []

    class FakeMem:
        async def read(self, **kwargs):
            read_calls.append(kwargs)
            return MagicMock(hot=[], warm={}, cold=[])

    monkeypatch.setattr(
        "packages.pipeline.nodes.load_memory.get_unified_memory_service",
        lambda tenant_id=None: FakeMem(),
    )
    from packages.pipeline.graph import build_pipeline

    graph = build_pipeline()
    final = await graph.ainvoke(make_initial_state("t1", "u1", "s1", "/help"))
    assert final.get("finish_reason") == "command_result"
    assert HELP_TEXT in (final.get("response") or "")
    assert read_calls == []
