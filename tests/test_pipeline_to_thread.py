"""S1a — sync DB/HTTP must leave the event loop."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from packages.memory.memory_service import UnifiedMemoryService
from packages.pipeline.state import make_initial_state
from packages.thread_pool import reset_thread_pool_for_tests


@pytest.fixture(autouse=True)
def _reset_pools() -> None:
    reset_thread_pool_for_tests()
    yield
    reset_thread_pool_for_tests()


@pytest.mark.asyncio
async def test_read_sync_db_does_not_block_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()

    def _slow_hot(self, **_k):  # noqa: ANN001
        started.set()
        time.sleep(0.3)
        return []

    async def _empty_warm(self, user_id: str):  # noqa: ANN001
        return {}, {}

    async def _empty_cold(self, user_id: str, session_id: str | None, cold_limit: int):  # noqa: ANN001
        return []

    monkeypatch.setattr(UnifiedMemoryService, "_read_hot_sync", _slow_hot)
    monkeypatch.setattr(UnifiedMemoryService, "_load_warm", _empty_warm)
    monkeypatch.setattr(UnifiedMemoryService, "_load_cold", _empty_cold)

    ticks: list[float] = []

    async def _heartbeat() -> None:
        while True:
            ticks.append(time.perf_counter())
            await asyncio.sleep(0.05)

    hb = asyncio.create_task(_heartbeat())
    svc = UnifiedMemoryService(tenant_id="t1")
    try:
        await svc.read(user_id="u1", session_id="s1")
    finally:
        hb.cancel()
        with pytest.raises(asyncio.CancelledError):
            await hb

    assert started.is_set()
    assert len(ticks) >= 3


@pytest.mark.asyncio
async def test_inject_list_session_runs_off_loop() -> None:
    from packages.attachments.inject import inject_session_attachments
    from packages.attachments.parse import AttachmentBlock
    from packages.attachments.store import MemoryAttachmentStore, set_attachment_store

    loop_ident = threading.get_ident()
    seen: dict[str, int] = {}

    store = MemoryAttachmentStore()
    store.save(
        tenant_id="t1",
        session_id="s1",
        uploaded_by="u1",
        name="a.pdf",
        media_type="application/pdf",
        size=10,
        status="ready",
        storage_path="/tmp/x",
        expired_at=None,
        blocks=[
            AttachmentBlock(
                block_index=0, kind="page", text="条款", char_count=2, page=1
            )
        ],
        attachment_id="a1",
    )
    orig_list = store.list_session
    orig_get = store.get

    def _list(*a, **k):  # noqa: ANN001
        seen["list"] = threading.get_ident()
        return orig_list(*a, **k)

    def _get(*a, **k):  # noqa: ANN001
        seen["get"] = threading.get_ident()
        return orig_get(*a, **k)

    store.list_session = _list  # type: ignore[method-assign]
    store.get = _get  # type: ignore[method-assign]
    set_attachment_store(store)
    try:
        state = make_initial_state("t1", "u1", "s1", "看附件")
        await inject_session_attachments(state)
    finally:
        set_attachment_store(None)

    assert seen.get("list") not in (None, loop_ident)
    assert seen.get("get") not in (None, loop_ident)
    assert state.get("file_blocks")
