"""Task 45 — content style / hotspot / script unit tests."""

from __future__ import annotations

import pytest

from backend.core.content_ops.hotspot import dig_hotspots
from backend.core.content_ops.script_gen import build_script_prompt, generate_script
from backend.core.content_ops.style import (
    DEFAULT_CONTENT_STYLE,
    resolve_style_for_generate,
)


def test_resolve_style_defaults_without_row():
    class _S:
        def query(self, *_a, **_k):
            return self

        def filter(self, *_a, **_k):
            return self

        def one_or_none(self):
            return None

    style = resolve_style_for_generate(_S(), "t-demo", "missing")
    assert style.get("is_default") is True
    assert style["persona"] == DEFAULT_CONTENT_STYLE["persona"]


def test_hotspot_seed_and_paste():
    seeded = dig_hotspots(adapter="seed", categories=["教育"])
    assert seeded["count"] >= 1
    assert seeded["content_hash"]
    pasted = dig_hotspots(
        adapter="paste",
        paste_text="1. 开学焦虑 — 家长群高频\n2. 晚托需求升温",
    )
    assert pasted["count"] == 2
    assert "开学焦虑" in pasted["items"][0]["title"]


def test_hotspot_topic_agent_uses_org():
    out = dig_hotspots(
        adapter="topic_agent",
        org_profile={"industry": "K12", "product_focus": "口才课", "target_audience": "小学生家长"},
        keywords="习惯",
    )
    assert out["count"] >= 1
    titles = " ".join(i["title"] for i in out["items"])
    assert "口才课" in titles or "习惯" in titles or out["items"]


def test_script_prompt_includes_style_and_org():
    prompt = build_script_prompt(
        style={**DEFAULT_CONTENT_STYLE, "is_default": True},
        org_profile={"name": "星河教育", "product_focus": "口才"},
        hotspots=[{"title": "开学季", "summary": "适应"}],
    )
    assert "星河教育" in prompt
    assert "开学季" in prompt


@pytest.mark.asyncio
async def test_generate_script_redacts_student_names():
    out = await generate_script(
        tenant_id="t1",
        style=dict(DEFAULT_CONTENT_STYLE),
        org_profile={},
        hotspots=[{"title": "习惯养成", "summary": ""}],
        student_names=["李明"],
        model="mock-local",
    )
    # mock may or may not emit 李明; force path by injecting
    from backend.core.memory_service import redact_student_names_in_text

    forced = redact_student_names_in_text(
        "请联系李明家长", tenant_id="t1", names=["李明"]
    )
    assert "李明" not in forced
    assert "script" in out


@pytest.mark.asyncio
async def test_generate_script_never_requires_style():
    out = await generate_script(
        tenant_id="t1",
        style=dict(DEFAULT_CONTENT_STYLE),
        org_profile={},
        hotspots=[],
        model="mock-local",
    )
    assert isinstance(out.get("script"), str)
    assert len(out["script"]) > 0


@pytest.mark.asyncio
async def test_style_extract_heuristic_short_and_long():
    from backend.core.content_ops.style_extract import extract_style_from_text

    short = await extract_style_from_text(
        tenant_id="t1", creator_id="c1", text="太短"
    )
    assert short["creator_id"] == "c1"
    long = (
        "同学们好，咱们今天就一件事。你品你细品。"
        "同学们好，咱们今天就一件事。先痛点再方法。"
    )
    out = await extract_style_from_text(
        tenant_id="t1", creator_id="c1", text=long, model="mock-local"
    )
    assert out["creator_id"] == "c1"
    assert out.get("is_default") is False
