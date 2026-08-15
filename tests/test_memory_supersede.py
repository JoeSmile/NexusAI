"""Task 41 S2b — supersede + correction sync."""

from __future__ import annotations

import asyncio

from backend.core.memory.extractor import RuleExtractor
from backend.core.memory.supersede import (
    bigram_jaccard,
    find_superseded_keys,
    same_topic,
)


def test_same_topic_by_normalized_slug() -> None:
    assert same_topic("preference:喜欢咖啡", "喜欢咖啡", "preference:喜欢咖啡", "喜欢拿铁")
    assert not same_topic("preference:喜欢咖啡", "喜欢咖啡", "fact:开会", "开会")


def test_same_topic_by_bigram() -> None:
    assert bigram_jaccard("喜欢美式咖啡啊", "喜欢美式咖啡") >= 0.8
    assert same_topic(
        "preference:喜欢美式咖",
        "喜欢美式咖啡啊",
        "preference:喜欢美式咖啡",
        "喜欢美式咖啡",
    )


def test_find_superseded_keys_excludes_new() -> None:
    existing = [
        ("preference:喜欢咖啡", "喜欢咖啡"),
        ("preference:喜欢茶", "喜欢茶"),
        ("fact:星火", "星火"),
    ]
    doomed = find_superseded_keys(
        existing=existing,
        new_key="preference:喜欢美式咖",
        new_value="喜欢咖啡",
    )
    assert "preference:喜欢咖啡" in doomed
    assert "preference:喜欢茶" not in doomed
    assert "preference:喜欢美式咖" not in doomed


def test_correction_phrase_extracts_sync() -> None:
    async def _run():
        return await RuleExtractor().extract(user_message="其实我喜欢红茶")

    cands = asyncio.run(_run())
    assert cands
    assert cands[0].sync is True
    assert cands[0].source == "correction"
    assert "红茶" in cands[0].value


def test_remember_strips_leading_comma() -> None:
    async def _run():
        return await RuleExtractor().extract(user_message="记住，开场先自我介绍")

    cands = asyncio.run(_run())
    assert cands
    assert not cands[0].value.startswith("，")
    assert not cands[0].value.startswith(",")
    assert "开场" in cands[0].value
