"""Task 78.2 — async rolling L1 summary via tenant LLM (mocked)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.memory.context_summarize import (
    SUMMARIZE_KIND,
    l1_warm_key,
    parse_l1_summary_json,
    run_l1_summarize,
)
from packages.memory.turn_archive import select_turn_ids_to_archive


def test_parse_l1_summary_accepts_schema() -> None:
    raw = json.dumps(
        {
            "summary": "用户在问汇丰流水",
            "key_facts": ["银行=汇丰"],
            "open_todos": [],
            "user_prefs": ["简洁"],
        },
        ensure_ascii=False,
    )
    out = parse_l1_summary_json(raw)
    assert out is not None
    assert out["summary"] == "用户在问汇丰流水"
    assert out["key_facts"] == ["银行=汇丰"]
    assert out["open_todos"] == []
    assert out["user_prefs"] == ["简洁"]


def test_parse_l1_summary_rejects_kernel_updates_and_belief() -> None:
    assert (
        parse_l1_summary_json(
            '{"summary":"x","key_facts":[],"open_todos":[],"user_prefs":[],'
            '"kernel_updates":{"slots":{}}}'
        )
        is None
    )
    assert (
        parse_l1_summary_json(
            '{"summary":"x","key_facts":[],"open_todos":[],"user_prefs":[],'
            '"belief":{}}'
        )
        is None
    )
    assert parse_l1_summary_json("not-json") is None
    assert parse_l1_summary_json("") is None


@pytest.mark.asyncio
async def test_run_l1_summarize_writes_warm_not_belief() -> None:
    audits: list[dict] = []
    mem = MagicMock()
    mem.write = AsyncMock(return_value={"id": 1})
    mem.read_archived_turns = MagicMock(
        return_value=[{"role": "user", "content": "查流水"}]
    )
    mem.read_l1_summary = MagicMock(return_value="")

    async def llm(**_k) -> str:
        return json.dumps(
            {
                "summary": "查流水",
                "key_facts": [],
                "open_todos": [],
                "user_prefs": [],
            }
        )

    with patch(
        "packages.intent.belief_store.set_belief"
    ) as set_belief, patch(
        "packages.intent.belief_store.delete_belief"
    ) as del_belief, patch(
        "packages.audit.write_audit_sync",
        side_effect=lambda r: audits.append(dict(r)) or True,
    ):
        code = await run_l1_summarize(
            {
                "tenant_id": "t1",
                "user_id": "u1",
                "session_id": "s1",
                "archived_ids": [9],
                "request_trace_id": "tr-1",
            },
            mem=mem,
            llm_call=llm,
            acquire_lock=lambda **_k: True,
            release_lock=lambda **_k: None,
        )
    assert code == "wrote"
    mem.write.assert_awaited()
    assert mem.write.await_args.args[0] == "warm"
    kwargs = mem.write.await_args.kwargs
    assert kwargs["key"] == l1_warm_key("s1")
    assert kwargs.get("embed") is False
    body = json.loads(kwargs["value"])
    assert body["summary"] == "查流水"
    assert "kernel_updates" not in body
    set_belief.assert_not_called()
    del_belief.assert_not_called()
    rec = next(a for a in audits if a.get("action") == "memory.l1_summarize")
    assert rec.get("error_code") in (None, "")
    assert "查流水" not in (rec.get("input_text") or "")
    assert rec.get("output_text") == "wrote"


@pytest.mark.asyncio
async def test_run_l1_summarize_skips_without_key() -> None:
    audits: list[dict] = []
    mem = MagicMock()
    mem.write = AsyncMock()
    mem.read_archived_turns = MagicMock(return_value=[{"role": "user", "content": "x"}])
    mem.read_l1_summary = MagicMock(return_value="")

    async def llm(**_k) -> str:
        raise AssertionError("llm must not run")

    with patch(
        "packages.audit.write_audit_sync",
        side_effect=lambda r: audits.append(dict(r)) or True,
    ):
        code = await run_l1_summarize(
            {
                "tenant_id": "t1",
                "user_id": "u1",
                "session_id": "s1",
                "archived_ids": [1],
            },
            mem=mem,
            llm_call=None,
            resolve_tenant_llm=lambda **_k: None,
            acquire_lock=lambda **_k: True,
            release_lock=lambda **_k: None,
        )
    assert code == "skipped_no_key"
    mem.write.assert_not_awaited()
    assert any(a.get("output_text") == "skipped_no_key" for a in audits)


@pytest.mark.asyncio
async def test_run_l1_summarize_skips_timeout_and_bad_json() -> None:
    mem = MagicMock()
    mem.write = AsyncMock()
    mem.read_archived_turns = MagicMock(return_value=[{"role": "user", "content": "x"}])
    mem.read_l1_summary = MagicMock(return_value="")

    async def boom(**_k) -> str:
        raise TimeoutError("slow")

    async def junk(**_k) -> str:
        return "NOT JSON"

    with patch("packages.audit.write_audit_sync", return_value=True):
        t = await run_l1_summarize(
            {
                "tenant_id": "t1",
                "user_id": "u1",
                "session_id": "s1",
                "archived_ids": [1],
            },
            mem=mem,
            llm_call=boom,
            acquire_lock=lambda **_k: True,
            release_lock=lambda **_k: None,
        )
        b = await run_l1_summarize(
            {
                "tenant_id": "t1",
                "user_id": "u1",
                "session_id": "s1",
                "archived_ids": [1],
            },
            mem=mem,
            llm_call=junk,
            acquire_lock=lambda **_k: True,
            release_lock=lambda **_k: None,
        )
    assert t == "skipped_timeout"
    assert b == "skipped_bad_json"
    mem.write.assert_not_awaited()


def test_write_memory_enqueues_summarize_for_archived_ids() -> None:
    from packages.memory.context_summarize import maybe_enqueue_l1_summarize

    with patch(
        "packages.memory.context_summarize.enqueue_memory_write",
        return_value="1-0",
    ) as enq:
        xid = maybe_enqueue_l1_summarize(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            archived_ids=[3, 4],
            trace_id="tr",
        )
    assert xid == "1-0"
    payload = enq.call_args.args[0]
    assert payload["kind"] == SUMMARIZE_KIND
    assert payload["archived_ids"] == [3, 4]
    assert "content" not in payload
    assert maybe_enqueue_l1_summarize(
        tenant_id="t1", user_id="u1", session_id="s1", archived_ids=[]
    ) is None


def test_select_overflow_still_independent() -> None:
    assert select_turn_ids_to_archive([(1, "a")], max_turns=10, budget_tokens=8000) == []
