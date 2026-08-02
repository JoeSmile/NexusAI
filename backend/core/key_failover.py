"""LLM Key 故障转移 — 429/401 切 key 重试 (Task 27)

5xx/超时不切 key(留给断路器)。错误分类看 HTTP status_code,不做字符串匹配。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar

from backend.core.key_repository import LLMKey, LLMKeyRepository

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 仅这些状态码触发切 key
_SWITCH_STATUS = frozenset({401, 429})


def classify_switchable_status(exc: BaseException) -> int | None:
    """若异常携带 401/429 HTTP 状态码则返回该码,否则 None。"""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in _SWITCH_STATUS:
        return status

    response = getattr(exc, "response", None)
    if response is not None:
        sc = getattr(response, "status_code", None)
        if isinstance(sc, int) and sc in _SWITCH_STATUS:
            return sc

    # openai.APIStatusError / httpx
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        # 不靠 message 字符串;仅当显式带 status 字段
        nested = body.get("status") or body.get("code")
        if nested in _SWITCH_STATUS:
            return int(nested)

    return None


def _audit_failover(
    *,
    tenant_id: str,
    provider: str,
    from_key_id: str,
    to_key_id: str,
    reason: str,
) -> None:
    try:
        from backend.core.audit import write_audit_sync

        write_audit_sync(
            {
                "tenant_id": tenant_id or "default",
                "user_id": "system",
                "action": "llm_key_failover",
                "trace_id": f"failover-{from_key_id}-{to_key_id}",
                "input_text": (
                    f"provider={provider} from={from_key_id} "
                    f"to={to_key_id} reason={reason}"
                ),
                "output_text": "",
                "model": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "latency_ms": 0.0,
                "error_code": reason,
                "ip_address": "",
                "user_agent": "",
                "created_at": datetime.utcnow(),
            }
        )
    except Exception:
        logger.debug("llm_key_failover audit write failed", exc_info=True)


async def call_with_key_failover(
    keys: list[LLMKey],
    call_fn: Callable[[str, str], Awaitable[T]],
    *,
    repo: LLMKeyRepository | None = None,
    tenant_id: str = "default",
    provider: str = "default",
) -> T:
    """
    按候选链调用 call_fn(api_key, base_url)。

    - 401/429 → mark_key_failed → 试下一个(最多 len(keys),且 ≤3)
    - 其它异常直接抛出(不切 key)
    - 成功 → clear_key_failure
    """
    if not keys:
        raise RuntimeError("无可用 LLM API Key 候选")

    repository = repo or LLMKeyRepository()
    chain = keys[:3]
    last_err: BaseException | None = None

    for i, key in enumerate(chain):
        try:
            result = await call_fn(key.api_key, key.base_url or "")
            await repository.clear_key_failure(key.id)
            return result
        except Exception as e:
            status = classify_switchable_status(e)
            if status is None:
                raise
            await repository.mark_key_failed(key.id)
            last_err = e
            next_key = chain[i + 1] if i + 1 < len(chain) else None
            if next_key is not None:
                _audit_failover(
                    tenant_id=tenant_id,
                    provider=provider or key.provider,
                    from_key_id=str(key.id),
                    to_key_id=str(next_key.id),
                    reason=str(status),
                )
                logger.warning(
                    "LLM key failover: %s → %s (HTTP %s)",
                    key.id,
                    next_key.id,
                    status,
                )
                continue
            break

    assert last_err is not None
    raise last_err


def call_with_key_failover_sync(
    keys: list[LLMKey],
    call_fn: Callable[[str, str], T],
    *,
    repo: LLMKeyRepository | None = None,
    tenant_id: str = "default",
    provider: str = "default",
) -> T:
    """同步版(供 complete_via_provider)。mark/clear 用 asyncio.run 包装。"""
    import asyncio

    if not keys:
        raise RuntimeError("无可用 LLM API Key 候选")

    repository = repo or LLMKeyRepository()
    chain = keys[:3]
    last_err: BaseException | None = None

    def _run(coro: Awaitable[Any]) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        # 已在事件循环中:同步路径尽量用后台线程跑
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()

    for i, key in enumerate(chain):
        try:
            result = call_fn(key.api_key, key.base_url or "")
            _run(repository.clear_key_failure(key.id))
            return result
        except Exception as e:
            status = classify_switchable_status(e)
            if status is None:
                raise
            _run(repository.mark_key_failed(key.id))
            last_err = e
            next_key = chain[i + 1] if i + 1 < len(chain) else None
            if next_key is not None:
                _audit_failover(
                    tenant_id=tenant_id,
                    provider=provider or key.provider,
                    from_key_id=str(key.id),
                    to_key_id=str(next_key.id),
                    reason=str(status),
                )
                continue
            break

    assert last_err is not None
    raise last_err
