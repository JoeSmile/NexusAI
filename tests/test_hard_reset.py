"""Task 78.3 — hard reset drops L1 narrative only; file_blocks billed separately."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from packages.attachments.parse import AttachmentBlock
from packages.attachments.store import MemoryAttachmentStore, set_attachment_store
from packages.intent.belief_store import get_belief, set_belief
from packages.memory.context_summarize import l1_warm_key
from packages.memory.hard_reset import drop_l1_narrative, maybe_hard_reset_l1
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


@pytest.fixture
def belief_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(
        "packages.intent.belief_store.get_sync_redis",
        lambda **_k: fake,
    )
    return fake


def test_drop_l1_narrative_does_not_touch_belief(belief_redis: _FakeRedis) -> None:
    set_belief(
        "t1",
        "u1",
        "s1",
        {"status": "ACTIVE", "slots": {"bank": "汇丰"}, "summary": "查流水"},
    )
    deleted: list[str] = []

    def _del(tenant_id: str, user_id: str, key: str) -> bool:
        deleted.append(key)
        return True

    with patch(
        "packages.memory.hard_reset.delete_user_memory", _del
    ), patch("packages.intent.belief_store.delete_belief") as del_belief:
        assert drop_l1_narrative("t1", "u1", "s1") is True
    assert deleted == [l1_warm_key("s1")]
    del_belief.assert_not_called()
    got = get_belief("t1", "u1", "s1")
    assert got is not None
    assert got["status"] == "ACTIVE"
    assert got["slots"]["bank"] == "汇丰"


def test_maybe_hard_reset_drops_l1_when_over_cap(belief_redis: _FakeRedis) -> None:
    set_belief("t1", "u1", "s1", {"status": "ACTIVE", "slots": {}, "summary": "订票"})
    with patch(
        "packages.memory.hard_reset.delete_user_memory", return_value=True
    ) as _del, patch.dict(
        "os.environ", {"MEMORY_HARD_RESET_TOKENS": "20"}, clear=False
    ):
        dropped = maybe_hard_reset_l1(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            unarchived_texts=["a" * 80, "b" * 80],
            l1_raw='{"summary":"' + ("x" * 80) + '"}',
        )
    assert dropped is True
    _del.assert_called_once()
    assert get_belief("t1", "u1", "s1")["status"] == "ACTIVE"


def test_maybe_hard_reset_skips_when_no_l1() -> None:
    with patch(
        "packages.memory.hard_reset.delete_user_memory", return_value=True
    ) as _del, patch.dict(
        "os.environ", {"MEMORY_HARD_RESET_TOKENS": "20"}, clear=False
    ):
        dropped = maybe_hard_reset_l1(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            unarchived_texts=["a" * 80, "b" * 80],
            l1_raw="",
        )
    assert dropped is False
    _del.assert_not_called()


def test_maybe_hard_reset_keeps_l1_under_cap() -> None:
    with patch(
        "packages.memory.hard_reset.delete_user_memory", return_value=True
    ) as _del, patch.dict(
        "os.environ", {"MEMORY_HARD_RESET_TOKENS": "8000"}, clear=False
    ):
        dropped = maybe_hard_reset_l1(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            unarchived_texts=["hi"],
            l1_raw='{"summary":"short"}',
        )
    assert dropped is False
    _del.assert_not_called()


@pytest.mark.asyncio
async def test_file_blocks_capped_separately_from_dialogue_window() -> None:
    from packages.attachments import inject as inj

    store = MemoryAttachmentStore()
    blocks = [
        AttachmentBlock(
            block_index=i,
            kind="page",
            text=f"page-{i}-" + ("合同条款" * 10),
            char_count=40,
            page=i + 1,
        )
        for i in range(20)
    ]
    store.save(
        tenant_id="t1",
        session_id="s1",
        uploaded_by="u1",
        name="big.pdf",
        media_type="application/pdf",
        size=100,
        status="ready",
        storage_path="/tmp/x",
        expired_at=datetime.now(UTC) + timedelta(days=7),
        blocks=blocks,
        attachment_id="big1",
    )
    set_attachment_store(store)
    truncated = {"n": 0}

    def _inc(n: int = 1) -> None:
        truncated["n"] += n

    try:
        with patch.object(inj, "MAX_INJECT_BLOCKS", 3), patch(
            "packages.attachments.inject.record_file_blocks_truncated", _inc
        ):
            state = make_initial_state("t1", "u1", "s1", "总结合同")
            await inj.inject_session_attachments(state)
        assert len(state["file_blocks"]) == 3
        assert truncated["n"] >= 1
        # Dialogue 8k budget is not used to squeeze file_blocks away:
        assert all("合同" in str(b.get("text") or "") for b in state["file_blocks"])
    finally:
        set_attachment_store(None)
