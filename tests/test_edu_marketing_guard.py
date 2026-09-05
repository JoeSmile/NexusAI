"""S3 — 教培营销红线（fail-open 替换）+ 漂移 profile + 四出口一致。"""

from __future__ import annotations

import json

import pytest

from packages.pipeline.state import make_initial_state

SAMPLE_LIVESTREAM_AD = (
    "家人们，这是全市最专业的课程，保证孩子提分，欢迎来直播间。"
)


@pytest.mark.asyncio
async def test_absolute_claims_rewritten_not_blocked():
    from packages.guardrails.generation_exit import sanitize_generation_exit

    result = await sanitize_generation_exit(
        SAMPLE_LIVESTREAM_AD,
        tenant_id="t-edu",
        profile="content_factory",
    )
    assert result.action != "blocked"
    text = result.redacted_text
    assert "最专业" not in text
    assert "保证孩子提分" not in text
    assert "家人们" in text
    assert "直播间" in text
    assert result.reason  # 有命中日志字段


@pytest.mark.asyncio
async def test_content_factory_allows_livestream_copy():
    from packages.guardrails.output_guard import check_output

    result = await check_output(
        "家人们，今晚直播间见，带你过一遍错题。",
        profile="content_factory",
    )
    assert result.action == "pass"


@pytest.mark.asyncio
async def test_secretary_still_blocks_livestream_copy():
    from packages.guardrails.output_guard import check_output

    result = await check_output(
        "家人们，今晚直播间见。",
        profile="secretary",
    )
    assert result.action == "blocked"
    assert "role_drift" in result.reason


@pytest.mark.asyncio
async def test_content_factory_still_blocks_scam_and_intimacy():
    from packages.guardrails.output_guard import check_output

    scam = await check_output("请把钱转到安全账户", profile="content_factory")
    assert scam.action == "blocked"
    love = await check_output("宝贝么么哒抱抱", profile="content_factory")
    assert love.action == "blocked"


@pytest.mark.asyncio
async def test_pipeline_long_path_allows_jia_ren_men():
    from packages.pipeline.nodes.guardrails_output import guardrails_output

    state = make_initial_state("t-edu", "u1", "s1", "写口播")
    state["response"] = SAMPLE_LIVESTREAM_AD
    out = await guardrails_output(state)
    assert out.get("finish_reason") != "blocked"
    assert "家人们" in (out.get("response") or "")
    assert "最专业" not in (out.get("response") or "")


@pytest.mark.asyncio
async def test_script_gen_rewrites_redlines(monkeypatch: pytest.MonkeyPatch):
    class _Harness:
        async def stream(self, **_kwargs):  # type: ignore[no-untyped-def]
            yield SAMPLE_LIVESTREAM_AD

    monkeypatch.setattr("packages.harness.LLMHarness", _Harness)
    from packages.content_ops.script_gen import generate_script
    from packages.content_ops.style import DEFAULT_CONTENT_STYLE

    out = await generate_script(
        tenant_id="t-edu",
        style=dict(DEFAULT_CONTENT_STYLE),
        org_profile={},
        hotspots=[{"title": "开学季", "summary": ""}],
        model="mock-local",
    )
    script = out["script"]
    assert "家人们" in script
    assert "最专业" not in script
    assert "保证孩子提分" not in script


@pytest.mark.asyncio
async def test_short_path_applies_same_sanitize():
    from packages.pipeline.nodes.model_router import apply_short_path_output_guards

    state = make_initial_state("t-edu", "u1", "s1", "写口播")
    state["response"] = SAMPLE_LIVESTREAM_AD
    out = await apply_short_path_output_guards(state)
    assert "家人们" in (out.get("response") or "")
    assert "最专业" not in (out.get("response") or "")


@pytest.mark.asyncio
async def test_workflow_node_exit_same_sanitize():
    from packages.workflow.node_exec import sanitize_workflow_answer

    text, meta = await sanitize_workflow_answer(
        SAMPLE_LIVESTREAM_AD,
        tenant_id="t-edu",
    )
    assert "家人们" in text
    assert "最专业" not in text
    assert "保证孩子提分" not in text
    assert meta.get("marketing_redline_hits")


@pytest.mark.asyncio
async def test_four_exits_same_text(monkeypatch: pytest.MonkeyPatch):
    from packages.content_ops.script_gen import generate_script
    from packages.content_ops.style import DEFAULT_CONTENT_STYLE
    from packages.guardrails.generation_exit import sanitize_generation_exit
    from packages.pipeline.nodes.guardrails_output import guardrails_output
    from packages.pipeline.nodes.model_router import apply_short_path_output_guards
    from packages.workflow.node_exec import sanitize_workflow_answer

    shared = await sanitize_generation_exit(
        SAMPLE_LIVESTREAM_AD,
        tenant_id="t-edu",
        profile="content_factory",
    )
    expected = shared.redacted_text

    state = make_initial_state("t-edu", "u1", "s1", "写口播")
    state["response"] = SAMPLE_LIVESTREAM_AD
    long_path = await guardrails_output(state)

    short_state = make_initial_state("t-edu", "u1", "s1", "写口播")
    short_state["response"] = SAMPLE_LIVESTREAM_AD
    short_path = await apply_short_path_output_guards(short_state)

    wf_text, _ = await sanitize_workflow_answer(
        SAMPLE_LIVESTREAM_AD, tenant_id="t-edu"
    )

    class _Harness:
        async def stream(self, **_kwargs):  # type: ignore[no-untyped-def]
            yield SAMPLE_LIVESTREAM_AD

    monkeypatch.setattr("packages.harness.LLMHarness", _Harness)
    gen = await generate_script(
        tenant_id="t-edu",
        style=dict(DEFAULT_CONTENT_STYLE),
        org_profile={},
        hotspots=[{"title": "开学季", "summary": ""}],
        model="mock-local",
    )

    assert long_path["response"] == expected
    assert short_path["response"] == expected
    assert wf_text == expected
    assert gen["script"] == expected


@pytest.mark.asyncio
async def test_g7_still_runs_on_shared_exit():
    from packages.guardrails.generation_exit import sanitize_generation_exit

    warm = {
        "entity:李明": json.dumps(
            {"name": "李明", "relation": "学生", "text": "李明"}
        )
    }
    result = await sanitize_generation_exit(
        "家人们，李明这周进步很大。",
        tenant_id="t-edu",
        profile="content_factory",
        warm=warm,
    )
    assert "李明" not in result.redacted_text
    assert "家人们" in result.redacted_text


def test_tenant_config_profile_secretary(monkeypatch: pytest.MonkeyPatch):
    from packages.guardrails import generation_exit as ge

    monkeypatch.setattr(ge, "_read_tenant_guard_profile", lambda _tid: "secretary")
    assert ge.resolve_output_guard_profile("t-hr") == "secretary"


def test_tenant_config_profile_defaults_content_factory(monkeypatch: pytest.MonkeyPatch):
    from packages.guardrails import generation_exit as ge

    monkeypatch.setattr(ge, "_read_tenant_guard_profile", lambda _tid: None)
    assert ge.resolve_output_guard_profile("t-new") == "content_factory"


@pytest.mark.asyncio
async def test_price_promises_rewritten():
    from packages.guardrails.generation_exit import sanitize_generation_exit

    result = await sanitize_generation_exit(
        "原价9980，现在立减，无效退款。",
        tenant_id="t-edu",
        profile="content_factory",
    )
    assert result.action != "blocked"
    text = result.redacted_text
    assert "原价" not in text
    assert "立减" not in text
    assert "无效退款" not in text

