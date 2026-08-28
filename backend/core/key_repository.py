"""
LLM API Key 数据库读写层。

职责:
  - 按租户+provider 查询可用 key / 候选链
  - 自动解密返回明文
  - LRU 缓存已解密 key
  - 失败冷却 / 连续失败摘除 (Task 27)
"""

from __future__ import annotations

import os
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


def _cooldown_seconds() -> int:
    try:
        from config import Config

        return int(getattr(Config, "KEY_COOLDOWN_SECONDS", 60) or 60)
    except Exception:
        return 60


def _max_consecutive_failures() -> int:
    try:
        from config import Config

        return int(getattr(Config, "KEY_MAX_CONSECUTIVE_FAILURES", 3) or 3)
    except Exception:
        return 3


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

    def _row_to_key(self, row: object) -> LLMKey:
        plain_key = self._manager().decrypt(row.encrypted_key)  # type: ignore[attr-defined]
        expires = getattr(row, "expires_at", None)
        return LLMKey(
            id=str(row.id),  # type: ignore[attr-defined]
            tenant_id=row.tenant_id,  # type: ignore[attr-defined]
            provider=row.provider,  # type: ignore[attr-defined]
            base_url=row.base_url or "",  # type: ignore[attr-defined]
            api_key=plain_key,
            key_version=int(row.key_version or 0),  # type: ignore[attr-defined]
            is_active=bool(row.is_active),  # type: ignore[attr-defined]
            expires_at=int(expires.timestamp()) if expires else None,
        )

    def _env_fallback(self, tenant_id: str, provider: str) -> LLMKey | None:
        from config import Config

        # EVID-17: env fallback 必须 spec 感知 — 按 provider 找 registry 模型,
        # 用它的 api_key_ref(如 QWEN_API_KEY)+ base_url(如百炼),否则 qwen key
        # 会被发到 LLM_BASE_URL(deepseek)端点 → 400。
        spec = None
        try:
            from packages.model_registry import get_registry

            spec = next(
                (s for s in get_registry().values() if s.provider == provider),
                None,
            )
        except Exception:
            spec = None

        key_ref = spec.api_key_ref if spec else None
        fallback: str = os.getenv(key_ref, "") if key_ref else ""
        if not fallback:
            fb_cfg: str | None = getattr(Config, "LLM_API_KEY_FALLBACK", None) or getattr(
                Config, "LLM_API_KEY", None
            )
            fallback = fb_cfg or ""
        if not fallback:
            return None
        base: str = ""
        if spec and spec.base_url:
            base = spec.base_url
        if not base:
            base_cfg: str | None = getattr(Config, "LLM_BASE_URL_FALLBACK", None) or getattr(
                Config, "LLM_BASE_URL", ""
            )
            base = base_cfg or ""
        return LLMKey(
            id="fallback",
            tenant_id=tenant_id,
            provider=provider,
            base_url=base or "",
            api_key=fallback,
            key_version=0,
            is_active=True,
            expires_at=None,
        )

    def _query_chain(
        self,
        session: object,
        tenant_id: str,
        provider: str,
        limit: int,
        cooldown: int,
    ) -> list:
        """查询未冷却的 active keys，按 key_version DESC。"""
        if limit <= 0:
            return []
        sql = text(
            """
            SELECT * FROM llm_api_keys
            WHERE tenant_id = :tid AND provider = :p AND is_active = true
              AND owner_user_id IS NULL
              AND (expires_at IS NULL OR expires_at > now())
              AND (
                last_failed_at IS NULL
                OR last_failed_at <= (now() - make_interval(secs => :cooldown))
              )
            ORDER BY key_version DESC
            LIMIT :lim
            """
        )
        return list(
            session.execute(  # type: ignore[attr-defined]
                sql,
                {
                    "tid": tenant_id,
                    "p": provider,
                    "cooldown": cooldown,
                    "lim": limit,
                },
            ).fetchall()
        )

    async def get_key_chain(
        self,
        tenant_id: str,
        provider: str = "default",
        limit: int = 3,
        *,
        allow_env_fallback: bool = True,
        tenant_only: bool = False,
    ) -> list[LLMKey]:
        """
        候选链: active + 未过期 + 不在冷却中,按 key_version DESC。

        回退顺序与 get_key 一致: tenant+provider → *+provider →
        tenant+default → *+default → env fallback。

        tenant_only=True: 仅查 tenant_id, 不回退 tenant_id='*' (Task 49 chat)。
        """
        lim = max(1, min(int(limit), 3))
        cooldown = _cooldown_seconds()
        collected: list[LLMKey] = []
        seen_ids: set[str] = set()

        pairs: list[tuple[str, str]] = [(tenant_id, provider)]
        if not tenant_only:
            pairs.append(("*", provider))
        if provider != "default":
            pairs.append((tenant_id, "default"))
            if not tenant_only:
                pairs.append(("*", "default"))

        session_factory = get_pg_session()
        with session_factory.Session() as session:
            for tid, p in pairs:
                if len(collected) >= lim:
                    break
                rows = self._query_chain(
                    session, tid, p, lim - len(collected), cooldown
                )
                for row in rows:
                    kid = str(row.id)
                    if kid in seen_ids:
                        continue
                    seen_ids.add(kid)
                    collected.append(self._row_to_key(row))
                    if len(collected) >= lim:
                        break

        if not collected and allow_env_fallback:
            fb = self._env_fallback(tenant_id, provider)
            if fb:
                return [fb]
        return collected

    async def get_key(
        self,
        tenant_id: str,
        provider: str = "default",
        *,
        allow_env_fallback: bool = True,
        tenant_only: bool = False,
    ) -> LLMKey | None:
        """薄封装:取候选链第一个(行为与改造前「最新 active」一致,另排除冷却中 key)。"""
        cache_key = f"{tenant_id}:{provider}:t{int(tenant_only)}:e{int(allow_env_fallback)}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        chain = await self.get_key_chain(
            tenant_id,
            provider,
            limit=1,
            allow_env_fallback=allow_env_fallback,
            tenant_only=tenant_only,
        )
        if not chain:
            return None
        key_obj = chain[0]
        if key_obj.id != "fallback":
            self._cache.set(cache_key, key_obj)
        return key_obj

    async def mark_key_failed(self, key_id: str | int) -> None:
        """连续失败 +1 并写入 last_failed_at;达阈值则 is_active=false。"""
        self.mark_key_failed_sync(key_id)

    def mark_key_failed_sync(self, key_id: str | int) -> None:
        """同步版（Wave G: sync failover 禁在事件循环里 asyncio.run/.result）。"""
        if str(key_id) == "fallback":
            return
        max_fail = _max_consecutive_failures()
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            session.execute(
                text(
                    """
                    UPDATE llm_api_keys
                    SET consecutive_failures = consecutive_failures + 1,
                        last_failed_at = now(),
                        is_active = CASE
                            WHEN consecutive_failures + 1 >= :max_fail THEN false
                            ELSE is_active
                        END
                    WHERE id = :id
                    """
                ),
                {"id": int(key_id), "max_fail": max_fail},
            )
            session.commit()
        self._cache = LLMKeyCache()

    async def clear_key_failure(self, key_id: str | int) -> None:
        """成功调用后归零失败计数与冷却。"""
        self.clear_key_failure_sync(key_id)

    def clear_key_failure_sync(self, key_id: str | int) -> None:
        if str(key_id) == "fallback":
            return
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            session.execute(
                text(
                    """
                    UPDATE llm_api_keys
                    SET consecutive_failures = 0,
                        last_failed_at = NULL
                    WHERE id = :id
                    """
                ),
                {"id": int(key_id)},
            )
            session.commit()

    def invalidate_cache(self, tenant_id: str, provider: str = "default") -> None:
        self._cache.invalidate(f"{tenant_id}:{provider}")
