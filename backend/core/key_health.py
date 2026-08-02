"""LLM API Key 健康检查 — 周期 verify + 连续失败自动摘除 / 恢复 (Task 27)"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import text

from backend.core.key_manager import KeyManager
from backend.core.key_repository import (
    LLMKeyRepository,
    _max_consecutive_failures,
)
from backend.database.pgvector_session import get_pg_session

logger = logging.getLogger(__name__)


def _audit_health(action: str, key_id: int, detail: str) -> None:
    try:
        from backend.core.audit import write_audit_sync

        write_audit_sync(
            {
                "tenant_id": "system",
                "user_id": "key_health",
                "action": action,
                "trace_id": f"key-health-{key_id}",
                "input_text": detail,
                "output_text": "",
                "model": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "latency_ms": 0.0,
                "error_code": None,
                "ip_address": "",
                "user_agent": "",
                "created_at": datetime.utcnow(),
            }
        )
    except Exception:
        logger.debug("key health audit failed", exc_info=True)


async def verify_key_by_id(key_id: int) -> dict:
    """验证单个 Key;失败走 mark_key_failed,成功复位并确保 is_active。"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        row = session.execute(
            text("SELECT * FROM llm_api_keys WHERE id = :id"),
            {"id": key_id},
        ).fetchone()
        if not row:
            return {"status": "not_found"}

        encrypted_key = row.encrypted_key
        base_url = row.base_url
        was_active = bool(row.is_active)

    km = KeyManager()
    plain_key = km.decrypt(encrypted_key)

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=plain_key, base_url=base_url or None)
        await client.models.list()
        ok = True
    except Exception:
        ok = False

    repo = LLMKeyRepository()
    if ok:
        with session_factory.Session() as session:
            session.execute(
                text(
                    """
                    UPDATE llm_api_keys
                    SET last_verified = now(),
                        last_verified_ok = true,
                        consecutive_failures = 0,
                        last_failed_at = NULL,
                        is_active = true
                    WHERE id = :id
                    """
                ),
                {"id": key_id},
            )
            session.commit()
        if not was_active:
            _audit_health(
                "llm_key_restored",
                key_id,
                f"key_id={key_id} verify ok → is_active=true",
            )
        return {"status": "ok", "key_id": key_id}

    # 失败:记录 verified_ok=false,再 mark(计数/达阈值摘除)
    with session_factory.Session() as session:
        session.execute(
            text(
                """
                UPDATE llm_api_keys
                SET last_verified = now(), last_verified_ok = false
                WHERE id = :id
                """
            ),
            {"id": key_id},
        )
        session.commit()

    await repo.mark_key_failed(key_id)

    # 若已达阈值被摘除,写审计
    with session_factory.Session() as session:
        row2 = session.execute(
            text(
                "SELECT is_active, consecutive_failures FROM llm_api_keys WHERE id = :id"
            ),
            {"id": key_id},
        ).fetchone()
        if row2 and not row2.is_active:
            _audit_health(
                "llm_key_deactivated",
                key_id,
                (
                    f"key_id={key_id} consecutive_failures="
                    f"{row2.consecutive_failures} ≥ {_max_consecutive_failures()}"
                ),
            )

    return {"status": "failed", "key_id": key_id}


class KeyHealthChecker:
    """定时检查 LLM API Key 状态"""

    CHECK_INTERVAL = 3600  # 每小时

    async def run_periodic_check(self) -> None:
        """后台循环 — 可挂到 FastAPI lifespan"""
        while True:
            await self._check_all()
            await asyncio.sleep(self.CHECK_INTERVAL)

    async def _check_all(self) -> None:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT id FROM llm_api_keys
                    WHERE (
                        expires_at IS NOT NULL AND expires_at < now() + interval '7 days'
                        OR last_verified IS NULL
                        OR last_verified < now() - interval '24 hours'
                        OR last_verified_ok = false
                      )
                    """
                )
            ).fetchall()

        for row in rows:
            await verify_key_by_id(row.id)
