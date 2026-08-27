"""Shared OpenAI httpx clients are process-level, not per request."""

from backend.core.openai_http import (
    _LIMITS,
    openai_async_http_client,
    openai_sync_http_client,
)


def test_shared_clients_are_singletons():
    a1 = openai_async_http_client()
    a2 = openai_async_http_client()
    s1 = openai_sync_http_client()
    s2 = openai_sync_http_client()
    assert a1 is a2
    assert s1 is s2
    assert not a1.is_closed
    assert not s1.is_closed
    assert _LIMITS.max_connections == 256
    assert _LIMITS.max_keepalive_connections == 64
