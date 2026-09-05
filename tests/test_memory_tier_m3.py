"""Task 89 M3 — warm 快路径补句式 + 每 8 轮异步 LLM 抽取。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from packages.memory.extractor import RuleExtractor


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


def test_remember_like_sugar_lands_warm() -> None:
    cands = asyncio_run(
        RuleExtractor().extract(user_message="记住我喜欢吃糖")
    )
    assert cands
    blob = " ".join(f"{c.key} {c.value}" for c in cands)
    assert "糖" in blob


def test_i_love_sugar_is_preference() -> None:
    cands = asyncio_run(RuleExtractor().extract(user_message="我爱吃糖"))
    assert len(cands) == 1
    assert cands[0].key.startswith("preference:")
    assert "糖" in cands[0].value


def test_dont_forget_like_sugar_lands_warm() -> None:
    cands = asyncio_run(
        RuleExtractor().extract(user_message="别忘了我喜欢吃糖")
    )
    assert cands
    blob = " ".join(f"{c.key} {c.value}" for c in cands)
    assert "糖" in blob


def test_enqueue_warm_extract_every_eight_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.memory import warm_llm_extract as w

    fake = MagicMock(return_value="1-0")
    monkeypatch.setattr(w, "enqueue_memory_write", fake)
    kw = dict(tenant_id="t", user_id="u", session_id="s", trace_id="tr")
    assert w.maybe_enqueue_warm_extract(user_turns=7, **kw) is None
    assert w.maybe_enqueue_warm_extract(user_turns=8, **kw) == "1-0"
    assert w.maybe_enqueue_warm_extract(user_turns=16, **kw) == "1-0"
    assert w.maybe_enqueue_warm_extract(user_turns=9, **kw) is None
    assert fake.call_count == 2
    payload = fake.call_args[0][0]
    assert payload["kind"] == w.WARM_EXTRACT_KIND


@pytest.mark.asyncio
async def test_run_warm_extract_writes_allergy_and_skips_bad_json() -> None:
    from packages.memory.warm_llm_extract import run_warm_extract

    writes: list[dict] = []

    class _Mem:
        def list_session_messages(self, **_k):
            return [{"role": "user", "content": "其实我对坚果过敏"}]

        async def write(self, tier, **payload):
            writes.append({"tier": tier, **payload})
            return {"id": 1, "tier": tier}

    async def llm_ok(**_k) -> str:
        return json.dumps(
            [
                {
                    "type": "fact",
                    "key": "fact:坚果过敏",
                    "value": "对坚果过敏",
                    "confidence": 0.8,
                }
            ],
            ensure_ascii=False,
        )

    code = await run_warm_extract(
        {
            "tenant_id": "t",
            "user_id": "u",
            "session_id": "s",
            "request_trace_id": "tr",
        },
        mem=_Mem(),
        llm_call=llm_ok,
        acquire_lock=lambda **_k: True,
        release_lock=lambda **_k: None,
    )
    assert code == "wrote"
    assert writes[0]["key"] == "fact:坚果过敏"
    assert "坚果" in writes[0]["value"]

    async def llm_bad(**_k) -> str:
        return "not-json"

    code2 = await run_warm_extract(
        {
            "tenant_id": "t",
            "user_id": "u",
            "session_id": "s",
        },
        mem=_Mem(),
        llm_call=llm_bad,
        acquire_lock=lambda **_k: True,
        release_lock=lambda **_k: None,
    )
    assert code2 == "skipped_bad_json"
