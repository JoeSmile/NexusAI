"""Task 35 — redis_tools 静默降级契约。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.core import redis_tools


@pytest.fixture(autouse=True)
def _reset_redis():
    redis_tools.reset_redis_clients_for_tests()
    yield
    redis_tools.reset_redis_clients_for_tests()


def test_get_sync_redis_degrades_when_ping_fails() -> None:
    boom = MagicMock()
    boom.ping.side_effect = ConnectionError("down")
    with patch.dict("sys.modules", {}):
        with patch("redis.Redis.from_url", return_value=boom):
            assert redis_tools.get_sync_redis() is None
            # 失败闩：第二次也不再重连
            assert redis_tools.get_sync_redis() is None
            assert boom.ping.call_count == 1


def test_cache_key_shape() -> None:
    assert redis_tools.cache_key("rag", "l1", "t1", "abc") == "rag:l1:t1:abc"


@pytest.mark.asyncio
async def test_get_async_redis_degrades() -> None:
    with patch(
        "redis.asyncio.from_url",
        side_effect=ConnectionError("down"),
    ):
        assert await redis_tools.get_async_redis() is None
        assert await redis_tools.get_async_redis() is None
