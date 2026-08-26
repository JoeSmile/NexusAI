"""Token 配额 — TPM / TPD（Task 72 切片 1）。

与 capability ``rl:cap:*`` 日桶分离（D6）：chat 主路径只用 ``tq:*``。
预检为保守估算；``record_token_usage`` 用实际上游 token 回填。
Redis 不可用 → check 静默放行（不 500）；record 失败只 log。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.core.cost_manager import count_message_tokens, count_tokens

logger = logging.getLogger(__name__)

_TPM_TTL_SEC = 120
_TPD_TTL_SEC = 86_400 * 2


@dataclass(frozen=True)
class TokenQuotaLimits:
    tpm: int
    tpd: int


def _env_int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def default_max_output_tokens() -> int:
    return _env_int("TOKEN_QUOTA_DEFAULT_MAX_OUTPUT", 1000)


def env_token_limits() -> TokenQuotaLimits:
    return TokenQuotaLimits(
        tpm=_env_int("TOKEN_QUOTA_TPM", 0),
        tpd=_env_int("TOKEN_QUOTA_TPD", 0),
    )


def _minute_bucket() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M")


def _day_bucket() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _redis():
    try:
        from backend.core.redis_tools import get_sync_redis

        return get_sync_redis(decode_responses=True)
    except Exception as exc:
        logger.debug("token quota redis unavailable: %s", exc)
        return None


def _tenant_limits_from_db(tenant_id: str) -> TokenQuotaLimits | None:
    """Optional override: ``tenant_config.config.token_quota``."""
    try:
        from sqlalchemy import text

        from backend.database.pgvector_session import get_pg_session

        session_factory = get_pg_session()
        with session_factory.Session() as session:
            row = session.execute(
                text("SELECT config FROM tenant_config WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            ).fetchone()
        if not row or not row.config:
            return None
        cfg = row.config if isinstance(row.config, dict) else {}
        tq = cfg.get("token_quota")
        if not isinstance(tq, dict):
            return None
        tpm = int(tq.get("tpm") or 0)
        tpd = int(tq.get("tpd") or 0)
        if tpm <= 0 and tpd <= 0:
            return None
        return TokenQuotaLimits(tpm=max(0, tpm), tpd=max(0, tpd))
    except Exception as exc:
        logger.debug("token quota tenant config skipped: %s", exc)
        return None


def resolve_token_limits(tenant_id: str) -> TokenQuotaLimits:
    override = _tenant_limits_from_db(tenant_id)
    if override is not None:
        return override
    return env_token_limits()


def estimate_request_tokens(state: dict[str, Any]) -> int:
    """保守预检：message + hot 历史 + warm/cold 摘要 + 默认 max_output。"""
    total = count_tokens(str(state.get("message") or ""))

    for item in state.get("hot_memory") or []:
        if isinstance(item, dict):
            total += count_message_tokens(item)

    warm = state.get("warm_memory")
    if isinstance(warm, dict):
        for val in warm.values():
            if isinstance(val, str):
                total += count_tokens(val)

    for item in state.get("cold_memory") or []:
        if isinstance(item, dict):
            text = item.get("content") or item.get("summary") or ""
            total += count_tokens(str(text))
        elif isinstance(item, str):
            total += count_tokens(item)

    mem_block = state.get("memory_prompt_block")
    if isinstance(mem_block, str) and mem_block.strip():
        total += count_tokens(mem_block)

    total += default_max_output_tokens()
    return max(1, total)


def check_token_quota(tenant_id: str, estimated_tokens: int) -> bool:
    """预检是否超限；True=允许。Redis 挂 → True。"""
    if estimated_tokens <= 0:
        return True
    limits = resolve_token_limits(tenant_id)
    if limits.tpm <= 0 and limits.tpd <= 0:
        return True

    client = _redis()
    if client is None:
        return True

    tid = tenant_id or "default"
    est = int(estimated_tokens)
    try:
        if limits.tpm > 0:
            tpm_key = f"tq:tpm:{tid}:{_minute_bucket()}"
            used = int(client.get(tpm_key) or 0)
            if used + est > limits.tpm:
                return False
        if limits.tpd > 0:
            tpd_key = f"tq:tpd:{tid}:{_day_bucket()}"
            used = int(client.get(tpd_key) or 0)
            if used + est > limits.tpd:
                return False
        return True
    except Exception as exc:
        logger.debug("token quota check skipped: %s", exc)
        return True


def record_token_usage(tenant_id: str, actual_tokens: int) -> None:
    """LLM 完成后累加实际 token（与 record_consumption 同点，不碰 rl:cap）。"""
    if actual_tokens <= 0:
        return
    limits = resolve_token_limits(tenant_id)
    if limits.tpm <= 0 and limits.tpd <= 0:
        return

    client = _redis()
    if client is None:
        return

    tid = tenant_id or "default"
    n = int(actual_tokens)
    try:
        if limits.tpm > 0:
            tpm_key = f"tq:tpm:{tid}:{_minute_bucket()}"
            cur = int(client.incrby(tpm_key, n))
            if cur == n:
                client.expire(tpm_key, _TPM_TTL_SEC)
        if limits.tpd > 0:
            tpd_key = f"tq:tpd:{tid}:{_day_bucket()}"
            cur = int(client.incrby(tpd_key, n))
            if cur == n:
                client.expire(tpd_key, _TPD_TTL_SEC)
    except Exception as exc:
        logger.debug("token quota record skipped: %s", exc)
