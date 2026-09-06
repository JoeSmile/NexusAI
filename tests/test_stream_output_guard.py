"""Task 90 — streaming output guard isomorphic with generation_exit."""

from __future__ import annotations

import json

import pytest

from packages.guardrails.stream_guard import (
    STREAM_BLOCK_PLACEHOLDER,
    apply_and_audit_stream_block,
    apply_stream_block_to_state,
    sanitize_streaming_chunk,
    student_names_from_warm,
    suffix_hold_len,
)
from packages.memory.memory_service import redact_student_names_in_text
from packages.pipeline.state import make_initial_state


def test_content_factory_allows_jia_ren_men_stream() -> None:
    delta, reason = sanitize_streaming_chunk(
        clean_so_far="",
        new_chunk="家人们，今晚直播间见。",
        tenant_id="t-edu",
        profile="content_factory",
        names=[],
    )
    assert reason == ""
    assert "家人们" in delta
    assert "直播间" in delta


def test_secretary_blocks_jia_ren_men_stream() -> None:
    delta, reason = sanitize_streaming_chunk(
        clean_so_far="今晚",
        new_chunk="家人们来直播间",
        tenant_id="t-sec",
        profile="secretary",
        names=[],
    )
    assert delta == ""
    assert reason.startswith("blocked:")
    assert "role_drift" in reason


def test_stream_blocks_api_key() -> None:
    delta, reason = sanitize_streaming_chunk(
        clean_so_far="",
        new_chunk="key=sk-abcdefghijklmnopqrstuvwxyz",
        tenant_id="t1",
        profile="content_factory",
        names=[],
    )
    assert delta == ""
    assert reason.startswith("blocked:")


def test_edu_redline_rewrites_not_abort() -> None:
    delta, reason = sanitize_streaming_chunk(
        clean_so_far="",
        new_chunk="本班保过提分，包过密卷。",
        tenant_id="t-edu",
        profile="content_factory",
        names=[],
    )
    assert not reason.startswith("blocked")
    assert "保过" not in delta
    assert "包过" not in delta
    assert delta


def test_g7_redacts_student_name_in_stream() -> None:
    names = ["张三"]
    alias = redact_student_names_in_text("张三", tenant_id="t1", names=names)
    delta, reason = sanitize_streaming_chunk(
        clean_so_far="",
        new_chunk="张三今天来上课",
        tenant_id="t1",
        profile="content_factory",
        names=names,
    )
    assert reason == ""
    assert "张三" not in delta
    assert alias in delta


def test_g7_holds_name_prefix_then_completes() -> None:
    names = ["张三"]
    alias = redact_student_names_in_text("张三", tenant_id="t1", names=names)
    d1, r1 = sanitize_streaming_chunk(
        clean_so_far="",
        new_chunk="张",
        tenant_id="t1",
        profile="content_factory",
        names=names,
    )
    assert r1 == ""
    assert "张" not in d1
    d2, r2 = sanitize_streaming_chunk(
        clean_so_far=d1,
        new_chunk="张三今天",
        tenant_id="t1",
        profile="content_factory",
        names=names,
    )
    assert r2 == ""
    assert "张三" not in (d1 + d2)
    assert alias in (d1 + d2)


def test_length_retracted() -> None:
    delta, reason = sanitize_streaming_chunk(
        clean_so_far="ab",
        new_chunk="cdefghij",
        tenant_id="t1",
        profile="content_factory",
        names=[],
        max_chars=5,
    )
    assert reason == "length_retracted"
    assert delta == "cde"
    assert len("ab" + delta) == 5


def test_student_names_from_warm() -> None:
    warm = {
        "entity:1": json.dumps({"relation": "学生", "name": "李四"}, ensure_ascii=False),
        "identity:name": "校长",
    }
    assert student_names_from_warm(warm) == ["李四"]


def test_apply_stream_block_placeholder() -> None:
    state = make_initial_state("t1", "u1", "s1", "hi")
    apply_stream_block_to_state(state, reason="blocked:role_drift:家人们")
    assert state["response"] == STREAM_BLOCK_PLACEHOLDER
    assert state["finish_reason"] == "blocked"


def test_apply_and_audit_stream_block(monkeypatch: pytest.MonkeyPatch) -> None:
    recs: list[dict] = []
    monkeypatch.setattr(
        "packages.audit.write_audit_sync",
        lambda rec: recs.append(rec),
    )
    state = make_initial_state("t1", "u1", "s1", "hi")
    apply_and_audit_stream_block(
        state, reason="blocked:role_drift:家人们", profile="secretary"
    )
    assert state["response"] == STREAM_BLOCK_PLACEHOLDER
    assert state["finish_reason"] == "blocked"
    assert recs
    assert recs[0]["action"] == "guardrails.stream_block"


def test_pending_hold_then_redact_like_router() -> None:
    from packages.guardrails.stream_guard import remaining_pending

    names = ["张三"]
    alias = redact_student_names_in_text("张三", tenant_id="t1", names=names)
    emitted = ""
    pending = ""
    for tok in ("张", "三今天来了"):
        pending += tok
        delta, reason = sanitize_streaming_chunk(
            clean_so_far=emitted,
            new_chunk=pending,
            tenant_id="t1",
            profile="content_factory",
            names=names,
        )
        new_pending = remaining_pending(emitted, pending, names)
        assert reason == ""
        emitted += delta
        pending = new_pending
    assert pending == ""
    assert "张三" not in emitted
    assert alias in emitted


def test_event_contract_abort_payload() -> None:
    from packages.guardrails.stream_guard import remaining_pending, stream_block_audit_record

    events: list[dict] = []
    emitted = ""
    pending = ""
    reason_out = ""
    for tok in ("今晚", "家人们来直播间"):
        pending += tok
        delta, reason = sanitize_streaming_chunk(
            clean_so_far=emitted,
            new_chunk=pending,
            tenant_id="t-sec",
            profile="secretary",
            names=[],
        )
        new_pending = remaining_pending(emitted, pending, [])
        if reason.startswith("blocked"):
            events.append({"type": "abort", "reason": "content_filter"})
            reason_out = reason
            break
        if delta:
            events.append({"token": delta})
            emitted += delta
        pending = new_pending
    events.append({"type": "done"})
    assert events[-2] == {"type": "abort", "reason": "content_filter"}
    assert events[-1] == {"type": "done"}
    state = make_initial_state("t-sec", "u1", "s1", "写口播")
    rec = stream_block_audit_record(state, reason=reason_out, profile="secretary")
    assert rec["action"] == "guardrails.stream_block"
    assert "role_drift" in rec["output_text"]


def test_suffix_hold_after_name_already_seen() -> None:
    assert suffix_hold_len("张三和张", ["张三"]) == 1


def _drive(tokens: list[str], *, profile: str, names: list[str], tenant_id: str = "t1"):
    from packages.guardrails.stream_guard import (
        flush_stream_guard,
        step_stream_guard,
    )

    emitted = ""
    unsent = ""
    events: list[dict] = []
    end_reason = ""
    for tok in tokens:
        unsent += tok
        delta, reason, unsent = step_stream_guard(
            emitted,
            unsent,
            tenant_id=tenant_id,
            profile=profile,
            names=names,
        )
        if reason.startswith("blocked"):
            events.append({"type": "abort", "reason": "content_filter"})
            end_reason = reason
            break
        if delta:
            events.append({"token": delta})
            emitted += delta
        if reason == "length_retracted":
            events.append({"type": "retraction", "reason": "length_exceeded"})
            end_reason = reason
            unsent = ""
            break
    if unsent and not end_reason.startswith("blocked"):
        delta, reason, unsent = flush_stream_guard(
            emitted,
            unsent,
            tenant_id=tenant_id,
            profile=profile,
            names=names,
        )
        if reason.startswith("blocked"):
            events.append({"type": "abort", "reason": "content_filter"})
            end_reason = reason
        else:
            if delta:
                events.append({"token": delta})
                emitted += delta
            if reason == "length_retracted":
                events.append({"type": "retraction", "reason": "length_exceeded"})
    events.append({"type": "done"})
    return events, emitted, end_reason


def test_drive_content_factory_jia_ren_men_tokens() -> None:
    events, emitted, reason = _drive(
        ["家", "人们，直播间见"],
        profile="content_factory",
        names=[],
        tenant_id="t-edu",
    )
    assert events[-1] == {"type": "done"}
    assert all(e.get("type") != "abort" for e in events)
    assert "家人们" in emitted
    assert "直播间" in emitted
    assert reason == ""


def test_drive_secretary_abort_before_done() -> None:
    events, _emitted, reason = _drive(
        ["今晚", "家人们来直播间"],
        profile="secretary",
        names=[],
        tenant_id="t-sec",
    )
    types = [e.get("type") for e in events]
    assert "abort" in types
    assert types.index("abort") < types.index("done")
    assert events[types.index("abort")] == {"type": "abort", "reason": "content_filter"}
    assert reason.startswith("blocked:")


def test_eos_flushes_held_marketing_suffix() -> None:
    events, emitted, reason = _drive(
        ["效果", "最"],
        profile="content_factory",
        names=[],
    )
    assert reason == ""
    assert all(e.get("type") != "abort" for e in events)
    assert emitted.endswith("最")


def test_second_name_prefix_does_not_abort() -> None:
    names = ["张三"]
    alias = redact_student_names_in_text("张三", tenant_id="t1", names=names)
    events, emitted, reason = _drive(
        ["张三和张", "三"],
        profile="content_factory",
        names=names,
    )
    assert all(e.get("type") != "abort" for e in events)
    assert reason == ""
    assert "张三" not in emitted
    assert not emitted.endswith("张")
    assert emitted.count(alias) >= 1


@pytest.mark.asyncio
async def test_generation_exit_still_allows_jia_ren_men() -> None:
    from packages.guardrails.generation_exit import sanitize_generation_exit

    result = await sanitize_generation_exit(
        "家人们，今晚直播间见。",
        tenant_id="t-edu",
        profile="content_factory",
    )
    assert result.action != "blocked"
    assert "家人们" in result.redacted_text
