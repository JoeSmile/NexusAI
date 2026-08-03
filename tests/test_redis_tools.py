"""Task 35/36 — redis_tools 静默降级 + 失败 TTL 重试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
    with patch("redis.Redis.from_url", return_value=boom):
        assert redis_tools.get_sync_redis() is None
        # TTL 内第二次也不再重连
        assert redis_tools.get_sync_redis() is None
        assert boom.ping.call_count == 1


def test_get_sync_redis_retries_after_ttl() -> None:
    boom = MagicMock()
    boom.ping.side_effect = ConnectionError("down")
    ok = MagicMock()
    ok.ping.return_value = True
    t0 = 1000.0
    with (
        patch("backend.core.redis_tools.time.monotonic", side_effect=[t0, t0 + 1.0]),
        patch("redis.Redis.from_url", return_value=boom),
    ):
        assert redis_tools.get_sync_redis() is None
        assert redis_tools.get_sync_redis() is None
        assert boom.ping.call_count == 1

    with (
        patch(
            "backend.core.redis_tools.time.monotonic",
            return_value=t0 + redis_tools.RETRY_AFTER_SEC + 1.0,
        ),
        patch("redis.Redis.from_url", return_value=ok),
    ):
        client = redis_tools.get_sync_redis()
        assert client is ok
        ok.ping.assert_called_once()


def test_close_sync_redis_clears_clients() -> None:
    ok = MagicMock()
    ok.ping.return_value = True
    with patch("redis.Redis.from_url", return_value=ok):
        assert redis_tools.get_sync_redis() is ok
    redis_tools.close_sync_redis()
    ok.close.assert_called_once()
    assert redis_tools._sync_clients == {}
    assert redis_tools._sync_failed == {}


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


@pytest.mark.asyncio
async def test_get_async_redis_retries_after_ttl() -> None:
    t0 = 2000.0
    with (
        patch("backend.core.redis_tools.time.monotonic", side_effect=[t0, t0 + 1.0]),
        patch(
            "redis.asyncio.from_url",
            side_effect=ConnectionError("down"),
        ),
    ):
        assert await redis_tools.get_async_redis() is None
        assert await redis_tools.get_async_redis() is None

    client = AsyncMock()
    client.ping = AsyncMock(return_value=True)
    with (
        patch(
            "backend.core.redis_tools.time.monotonic",
            return_value=t0 + redis_tools.RETRY_AFTER_SEC + 1.0,
        ),
        patch("redis.asyncio.from_url", return_value=client),
    ):
        got = await redis_tools.get_async_redis()
        assert got is client
        client.ping.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_async_redis_clears_failed() -> None:
    with patch(
        "redis.asyncio.from_url",
        side_effect=ConnectionError("down"),
    ):
        assert await redis_tools.get_async_redis() is None
    assert redis_tools._async_failed
    await redis_tools.close_async_redis()
    assert redis_tools._async_failed == {}
    assert redis_tools._async_clients == {}
