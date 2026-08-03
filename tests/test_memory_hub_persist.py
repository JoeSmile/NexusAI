"""Task 34.04 — MemoryHub PersistentScopedStore 持久化视图。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.agent.memory_hub import MemoryHub, get_memory_hub, reset_memory_hub
from backend.agent.memory_store import PersistentScopedStore, hub_warm_key
from backend.core.memory_service import MemoryBundle


@pytest.fixture(autouse=True)
def _reset_hubs():
    reset_memory_hub()
    yield
    reset_memory_hub()


@pytest.mark.asyncio
async def test_persistent_store_write_calls_store_user_memory() -> None:
    store = PersistentScopedStore(
        store_id="u_test",
        scope="user",
        target_id="u1",
        tenant_id="t1",
        user_id="u1",
        persist=True,
    )
    with patch(
        "backend.database.vector_ops.store_user_memory", return_value=7
    ) as m:
        entry = await store.write("preferences/tone", "formal")
    assert entry.content == "formal"
    m.assert_called_once()
    kwargs = m.call_args.kwargs
    assert kwargs["key"] == hub_warm_key("user", "preferences/tone")
    assert kwargs["value"] == "formal"
    assert kwargs["tenant_id"] == "t1"


@pytest.mark.asyncio
async def test_persistent_store_hydrate_from_unified_read() -> None:
    store = PersistentScopedStore(
        store_id="u_test",
        scope="user",
        target_id="u1",
        tenant_id="t1",
        user_id="u1",
        persist=True,
    )
    key = hub_warm_key("user", "preferences/tone")
    bundle = MemoryBundle(warm={key: "formal", "other": "x"})

    class _Ums:
        async def read(self, **_k):
            return bundle

    with patch(
        "backend.core.memory_service.get_unified_memory_service",
        return_value=_Ums(),
    ):
        n = await store.hydrate()
    assert n == 1
    entry = await store.read("preferences/tone")
    assert entry is not None
    assert entry.content == "formal"


@pytest.mark.asyncio
async def test_memory_hub_survives_reinit_via_hydrate() -> None:
    persisted: dict[str, str] = {}

    def fake_store(**kwargs):
        persisted[kwargs["key"]] = kwargs["value"]
        return 1

    with patch(
        "backend.database.vector_ops.store_user_memory", side_effect=fake_store
    ):
        hub1 = MemoryHub(
            user_id="u1", session_id="s1", tenant_id="t1", agent_type="cg"
        )
        await hub1.user_store.write("context/current_task", "risk-review")

    class _Ums:
        async def read(self, **_k):
            return MemoryBundle(warm=dict(persisted))

    with patch(
        "backend.core.memory_service.get_unified_memory_service",
        return_value=_Ums(),
    ):
        hub2 = MemoryHub(
            user_id="u1", session_id="s1", tenant_id="t1", agent_type="cg"
        )
        await hub2.initialize()
        entry = await hub2.user_store.read("context/current_task")
    assert entry is not None
    assert entry.content == "risk-review"


def test_get_memory_hub_isolates_by_tenant() -> None:
    a = get_memory_hub(user_id="u", session_id="s", tenant_id="t1")
    b = get_memory_hub(user_id="u", session_id="s", tenant_id="t2")
    assert a is not b
    assert a._tenant_id == "t1"
    assert b._tenant_id == "t2"
