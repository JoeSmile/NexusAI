"""
LLM API Key 数据库读写层。

职责:
  - 按租户+provider 查询可用 key
  - 自动解密返回明文
  - LRU 缓存已解密 key
  - 支持 key 版本 / 过期检测
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import text

from backend.core.key_manager import KeyManager
from backend.database.pgvector_session import get_pg_session


@dataclass
class LLMKey:
    id: str
    tenant_id: str
    provider: str
    base_url: str
    api_key: str  # 已解密明文
    key_version: int
    is_active: bool
    expires_at: int | None  # Unix timestamp


class LLMKeyCache:
    """LRU 缓存，已解密 key 不进日志"""

    MAX = 100
    TTL_SEC = 300

    def __init__(self) -> None:
        self._cache: OrderedDict[str, tuple[LLMKey, float]] = OrderedDict()

    def get(self, key: str) -> LLMKey | None:
        item = self._cache.get(key)
        if not item:
            return None
        key_obj, ts = item
        if time.time() - ts > self.TTL_SEC:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return key_obj

    def set(self, key: str, value: LLMKey) -> None:
        self._cache[key] = (value, time.time())
        if len(self._cache) > self.MAX:
            self._cache.popitem(last=False)

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)


class LLMKeyRepository:
    """按租户+provider 获取 LLM API Key，自动解密"""

    def __init__(self, key_manager: KeyManager | None = None):
        self._km = key_manager
        self._cache = LLMKeyCache()

    def _manager(self) -> KeyManager:
        if self._km is None:
            self._km = KeyManager()
        return self._km

    async def get_key(
        self, tenant_id: str, provider: str = "default"
    ) -> LLMKey | None:
        """查询: 租户专用 key → 全局默认 key → env fallback"""
        cache_key = f"{tenant_id}:{provider}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        session_factory = get_pg_session()
        with session_factory.Session() as session:
            sql = text(
                """
                SELECT * FROM llm_api_keys
                WHERE tenant_id = :tid AND provider = :p AND is_active = true
                  AND (expires_at IS NULL OR expires_at > now())
                ORDER BY key_version DESC LIMIT 1
                """
            )
            row = session.execute(sql, {"tid": tenant_id, "p": provider}).fetchone()

            if not row:
                row = session.execute(sql, {"tid": "*", "p": provider}).fetchone()

            if not row and provider != "default":
                row = session.execute(
                    sql, {"tid": tenant_id, "p": "default"}
                ).fetchone()
            if not row and provider != "default":
                row = session.execute(sql, {"tid": "*", "p": "default"}).fetchone()

            if not row:
                from config import Config

                fallback = getattr(Config, "LLM_API_KEY_FALLBACK", None) or getattr(
                    Config, "LLM_API_KEY", None
                )
                if fallback:
                    return LLMKey(
                        id="fallback",
                        tenant_id=tenant_id,
                        provider=provider,
                        base_url=getattr(Config, "LLM_BASE_URL_FALLBACK", None)
                        or getattr(Config, "LLM_BASE_URL", "")
                        or "",
                        api_key=fallback,
                        key_version=0,
                        is_active=True,
                        expires_at=None,
                    )
                return None

            plain_key = self._manager().decrypt(row.encrypted_key)
            key_obj = LLMKey(
                id=str(row.id),
                tenant_id=row.tenant_id,
                provider=row.provider,
                base_url=row.base_url or "",
                api_key=plain_key,
                key_version=row.key_version,
                is_active=row.is_active,
                expires_at=int(row.expires_at.timestamp()) if row.expires_at else None,
            )
            self._cache.set(cache_key, key_obj)
            return key_obj

    def invalidate_cache(self, tenant_id: str, provider: str = "default") -> None:
        self._cache.invalidate(f"{tenant_id}:{provider}")
