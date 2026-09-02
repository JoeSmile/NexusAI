"""Task 45b.5B — topic brief: unverified numbers, script prompt, bili fail-open."""

from __future__ import annotations

import pytest

from packages.content_ops.script_gen import build_script_prompt
from packages.content_ops.style import DEFAULT_CONTENT_STYLE


def test_unverified_numbers_get_official_caveat() -> None:
    from packages.content_ops.topic_brief import annotate_unverified_numbers

    out = annotate_unverified_numbers("录取率约32%，比去年高。")
    assert "32" in out
    assert "待核实" in out
    assert "官方" in out


def test_already_caveated_text_not_doubled() -> None:
    from packages.content_ops.topic_brief import annotate_unverified_numbers

    src = "报名人数以官方为准，待核实后再引用。"
    assert annotate_unverified_numbers(src) == src


def test_script_prompt_includes_brief_block() -> None:
    prompt = build_script_prompt(
        style=dict(DEFAULT_CONTENT_STYLE),
        org_profile={"name": "星河教育"},
        hotspots=[{"title": "专升本报名", "summary": "窗口将至"}],
        brief={
            "title": "专升本报名",
            "summary": "窗口将至",
            "key_points": ["政策以省级教育考试院为准"],
            "risks": ["数据待核实，以官方为准"],
        },
    )
    assert "【素材简报】" in prompt
    assert "省级教育考试院" in prompt
    assert "专升本报名" in prompt


@pytest.mark.asyncio
async def test_bilibili_failure_still_returns_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.content_ops import topic_brief as tb

    monkeypatch.setattr(tb, "search_bilibili_topics", lambda *_a, **_k: [])

    class _H:
        async def generate(self, **_k):
            from packages.harness.base import HarnessResult

            return HarnessResult(
                output=(
                    '{"background":"政策以官方为准","key_points":["关注省级简章"],'
                    '"misconceptions":["不要轻信录取率传闻"],'
                    '"case_directions":["讲备考节奏而非某考生"],'
                    '"risks":["数据待核实，以官方为准"]}'
                ),
                success=True,
                metadata={},
            )

    monkeypatch.setattr(tb, "_harness", lambda: _H())
    out = await tb.generate_topic_brief(
        tenant_id="t1",
        user_id="u1",
        title="专升本报名",
        summary="窗口将至",
        persist=False,
    )
    assert out["kind"] == "brief"
    assert out.get("bilibili") == []
    assert out.get("key_points")
    assert any("待核实" in str(x) for x in (out.get("risks") or [out.get("background") or ""]))
