"""Task 76.0 — exact cache bypass for follow-ups and session attachments."""

from __future__ import annotations

import pytest

from packages.pipeline.followup_lexicon import is_followup_utterance
from packages.pipeline.nodes.preprocess import preprocess, should_cache_bypass
from packages.pipeline.state import make_initial_state

_REQUIRED = (
    "继续",
    "然后呢",
    "嗯",
    "好的",
    "是的",
    "对",
    "接着说",
    "还有呢",
    "后来呢",
    "那然后",
    "明天呢",
)


def test_followup_lexicon_required_utterances() -> None:
    for w in _REQUIRED:
        assert is_followup_utterance(w), w
    assert is_followup_utterance("明天呢？")
    assert is_followup_utterance(" 好的。 ")
    assert is_followup_utterance("「明天呢」")


def test_followup_lexicon_does_not_substring_or_hit_greeting() -> None:
    assert not is_followup_utterance("你好")
    assert not is_followup_utterance("今天天气怎么样")
    assert not is_followup_utterance("北京天气")
    assert not is_followup_utterance("对冲基金怎么样")
    assert not is_followup_utterance("总结一下")
    assert not is_followup_utterance("")


def test_content_factory_bypass_still_independent() -> None:
    assert should_cache_bypass("看看今天有什么热点")
    assert not should_cache_bypass("明天呢")
    assert not should_cache_bypass("你好")


@pytest.mark.asyncio
async def test_preprocess_followup_sets_cache_bypass() -> None:
    out = await preprocess(make_initial_state("t1", "u1", "s1", "明天呢"))
    assert out["cache_bypass"] is True
    assert out["finish_reason"] != "blocked"


@pytest.mark.asyncio
async def test_preprocess_beijing_weather_does_not_bypass() -> None:
    out = await preprocess(make_initial_state("t1", "u1", "s1", "北京天气"))
    assert out["cache_bypass"] is False


@pytest.mark.asyncio
async def test_preprocess_hotspot_or_followup() -> None:
    hot = await preprocess(make_initial_state("t1", "u1", "s1", "生成教育热点选题"))
    assert hot["cache_bypass"] is True
    follow = await preprocess(make_initial_state("t1", "u1", "s1", "继续"))
    assert follow["cache_bypass"] is True


@pytest.mark.asyncio
async def test_preprocess_ready_attachments_bypass_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "packages.pipeline.nodes.preprocess.session_has_ready_attachments",
        lambda *_a, **_k: True,
    )
    out = await preprocess(make_initial_state("t1", "u1", "s1", "总结一下"))
    assert out["cache_bypass"] is True


@pytest.mark.asyncio
async def test_preprocess_no_attachments_summary_does_not_bypass() -> None:
    out = await preprocess(make_initial_state("t1", "u1", "s1", "总结一下"))
    assert out["cache_bypass"] is False


@pytest.mark.asyncio
async def test_cache_check_skips_stale_exact_when_followup_bypassed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.pipeline.nodes.cache_check import cache_check

    def _must_not_hit_db() -> None:
        raise AssertionError("cache_check must not query exact when bypassed")

    monkeypatch.setattr(
        "packages.pipeline.nodes.cache_check.get_pg_session",
        _must_not_hit_db,
    )
    state = await preprocess(make_initial_state("t1", "u1", "s1", "明天呢"))
    assert state["cache_bypass"] is True
    out = await cache_check(state)
    assert out.get("cache_hit") is False
    assert out.get("finish_reason") != "cache_hit"


class _ValueRow:
    def __init__(self, value: str) -> None:
        self.value = value


class _SessionCM:
    def __init__(self, rows: list[object | None]) -> None:
        self._rows = list(rows)

    def __enter__(self) -> _SessionCM:
        return self

    def __exit__(self, *a: object) -> bool:
        return False

    def execute(self, *a: object, **k: object) -> object:
        row = self._rows.pop(0) if self._rows else None

        class _Result:
            def fetchone(self) -> object:
                return row

        return _Result()


class _SessionFactory:
    def __init__(self, rows: list[object | None]) -> None:
        self._rows = rows

    def Session(self) -> _SessionCM:
        return _SessionCM(self._rows)


@pytest.mark.asyncio
async def test_cache_check_sets_cache_type_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.pipeline.nodes.cache_check import cache_check

    monkeypatch.setattr(
        "packages.pipeline.nodes.cache_check.get_pg_session",
        lambda: _SessionFactory([_ValueRow("cached-exact")]),
    )
    state = make_initial_state("t1", "u1", "s1", "北京天气")
    state["query_hash"] = "qh1"
    out = await cache_check(state)
    assert out["cache_hit"] is True
    assert out["cache_type"] == "exact"
    assert out["finish_reason"] == "cache_hit"


@pytest.mark.asyncio
async def test_cache_check_sets_cache_type_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.pipeline.nodes.cache_check import cache_check

    monkeypatch.setattr(
        "packages.pipeline.nodes.cache_check.get_pg_session",
        lambda: _SessionFactory([None, _ValueRow("cached-hi")]),
    )
    state = make_initial_state("t1", "u1", "s1", "你好")
    state["query_hash"] = "qh2"
    out = await cache_check(state)
    assert out["cache_hit"] is True
    assert out["cache_type"] == "template"
    assert out["finish_reason"] == "cache_hit"
