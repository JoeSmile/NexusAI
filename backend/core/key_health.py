"""LLM API Key 健康检查"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from backend.core.key_manager import KeyManager
from backend.database.pgvector_session import get_pg_session


async def verify_key_by_id(key_id: int) -> dict:
    """验证单个 Key"""
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

    km = KeyManager()
    plain_key = km.decrypt(encrypted_key)

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=plain_key, base_url=base_url or None)
        await client.models.list()
        ok = True
    except Exception:
        ok = False

    with session_factory.Session() as session:
        session.execute(
            text(
                """
                UPDATE llm_api_keys
                SET last_verified = now(), last_verified_ok = :ok
                WHERE id = :id
                """
            ),
            {"ok": ok, "id": key_id},
        )
        session.commit()

    return {"status": "ok" if ok else "failed", "key_id": key_id}


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
                    WHERE is_active = true
                      AND (
                        expires_at IS NOT NULL AND expires_at < now() + interval '7 days'
                        OR last_verified IS NULL
                        OR last_verified < now() - interval '24 hours'
                      )
                    """
                )
            ).fetchall()

        for row in rows:
            await verify_key_by_id(row.id)
