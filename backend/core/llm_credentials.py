"""Tenant LLM credential resolution (industry-standard single-model rows)."""

from __future__ import annotations

from sqlalchemy import text

from packages.errors import ErrorCode, NexusAIException
from packages.key_manager import KeyManager
from packages.key_repository import LLMKey
from backend.database.pgvector_session import get_pg_session

_LLM_KEY_MISSING = ErrorCode.LLM_KEY_MISSING.value
_LLM_MODEL_NOT_ALLOWED = ErrorCode.LLM_MODEL_NOT_ALLOWED.value

PURPOSE_CHAT = "chat"
PURPOSE_EMBEDDING = "embedding"
_LEGACY_CHAT_PROVIDERS = frozenset({"deepseek", "qwen", "dashscope", "tongyi", "default"})

_TENANT_KEY_ROWS_SQL = text(
    """
    SELECT id, tenant_id, provider, allowed_models, base_url, encrypted_key,
           key_version, is_active, expires_at
    FROM llm_api_keys
    WHERE tenant_id = :tid AND is_active = true
      AND owner_user_id IS NULL
      AND (expires_at IS NULL OR expires_at > now())
    """
)

_TENANT_KEY_CHAIN_SQL = text(
    """
    SELECT id, tenant_id, provider, allowed_models, base_url, encrypted_key,
           key_version, is_active, expires_at
    FROM llm_api_keys
    WHERE tenant_id = :tid AND is_active = true
      AND owner_user_id IS NULL
      AND (expires_at IS NULL OR expires_at > now())
      AND (
        last_failed_at IS NULL
        OR last_failed_at <= (now() - make_interval(secs => :cooldown))
      )
    ORDER BY key_version DESC
    """
)

EMBEDDING_DIMENSIONS = 768


def normalize_purpose(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s in (PURPOSE_CHAT, PURPOSE_EMBEDDING):
        return s
    if s in _LEGACY_CHAT_PROVIDERS or s.startswith("deepseek") or s.startswith("qwen"):
        return PURPOSE_CHAT
    raise ValueError(f"unsupported_purpose:{raw}")


def is_chat_purpose(provider: str) -> bool:
    try:
        return normalize_purpose(provider) == PURPOSE_CHAT
    except ValueError:
        # Unknown legacy vendor labels still treated as chat for list/resolve
        return (provider or "").strip().lower() != PURPOSE_EMBEDDING


def is_embedding_purpose(provider: str) -> bool:
    return (provider or "").strip().lower() == PURPOSE_EMBEDDING


def _model_allowed(allowed_models: object, model: str) -> bool:
    if not isinstance(allowed_models, list):
        return False
    for raw in allowed_models:
        if isinstance(raw, str) and raw.strip() == model:
            return True
    return False


def _primary_model(allowed_models: object) -> str | None:
    if not isinstance(allowed_models, list):
        return None
    for raw in allowed_models:
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _row_to_key(row: object, km: KeyManager | None = None) -> LLMKey:
    manager = km or KeyManager()
    plain = manager.decrypt(row.encrypted_key)  # type: ignore[attr-defined]
    expires = getattr(row, "expires_at", None)
    return LLMKey(
        id=str(row.id),  # type: ignore[attr-defined]
        tenant_id=row.tenant_id,  # type: ignore[attr-defined]
        provider=str(row.provider),  # type: ignore[attr-defined]
        base_url=(row.base_url or "") if getattr(row, "base_url", None) else "",  # type: ignore[attr-defined]
        api_key=plain,
        key_version=int(row.key_version or 0),  # type: ignore[attr-defined]
        is_active=bool(row.is_active),  # type: ignore[attr-defined]
        expires_at=int(expires.timestamp()) if expires else None,
    )


def _fetch_tenant_rows(tenant_id: str) -> list:
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        return list(session.execute(_TENANT_KEY_ROWS_SQL, {"tid": tenant_id}).fetchall())


def _fetch_tenant_chain_rows(tenant_id: str, cooldown: int) -> list:
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        return list(
            session.execute(
                _TENANT_KEY_CHAIN_SQL,
                {"tid": tenant_id, "cooldown": int(cooldown)},
            ).fetchall()
        )


def _key_cooldown_seconds() -> int:
    try:
        from packages.key_repository import _cooldown_seconds

        return int(_cooldown_seconds())
    except Exception:
        return 60


async def get_key_chain_for_model(
    tenant_id: str,
    model: str,
    *,
    limit: int = 3,
) -> list[LLMKey]:
    """Model-scoped key chain: chat-purpose rows + allowed_models match + cooldown.

    Tenant-only; no env fallback (Task 49 / Task 72).
    """
    model = (model or "").strip()
    if not model:
        return []
    lim = max(1, min(int(limit), 3))
    cooldown = _key_cooldown_seconds()
    chain: list[LLMKey] = []
    seen: set[str] = set()
    for row in _fetch_tenant_chain_rows(tenant_id, cooldown):
        if not is_chat_purpose(str(row.provider)):
            continue
        if not _model_allowed(row.allowed_models, model):
            continue
        kid = str(row.id)
        if kid in seen:
            continue
        seen.add(kid)
        key = _row_to_key(row)
        chain.append(key)
        if len(chain) >= lim:
            break
    return chain


async def list_available_models(tenant_id: str) -> list[dict]:
    """Chat models only — from active chat-purpose credentials."""
    items: list[dict] = []
    seen: set[str] = set()
    for row in _fetch_tenant_rows(tenant_id):
        if not is_chat_purpose(str(row.provider)):
            continue
        model_name = _primary_model(row.allowed_models)
        if not model_name or model_name in seen:
            continue
        seen.add(model_name)
        items.append(
            {
                "model": model_name,
                "series": PURPOSE_CHAT,
                "configured": True,
            }
        )
    return items


async def resolve_chat_model_for_request(
    tenant_id: str,
    requested: str | None,
) -> str:
    """Pick tenant chat model: honor valid request; else auto first/only configured."""
    items = await list_available_models(tenant_id)
    names = [str(i["model"]) for i in items if i.get("model")]
    req = (requested or "").strip()
    if req and req in names:
        return req
    if not names:
        raise NexusAIException(
            ErrorCode.LLM_MODEL_REQUIRED.value,
            "tenant_llm_key_missing",
            detail="Ask tenant admin to configure LLM credentials",
        )
    if req and req not in names:
        return names[0]
    return names[0]


async def resolve_tenant_credential(tenant_id: str, model: str) -> LLMKey:
    """Resolve chat credential by exact model name; no env fallback."""
    from packages.llm_key_pool import pick_key_from_chain

    model = (model or "").strip()
    if not model:
        raise NexusAIException(_LLM_MODEL_NOT_ALLOWED, "model_not_allowed")

    chain = await get_key_chain_for_model(tenant_id, model, limit=3)
    if not chain:
        raise NexusAIException(_LLM_MODEL_NOT_ALLOWED, "model_not_allowed")

    key = pick_key_from_chain(chain, tenant_id=tenant_id, model=model)
    if key is None or not key.base_url:
        raise NexusAIException(_LLM_KEY_MISSING, "tenant_llm_base_url_missing")
    return key


async def resolve_embedding_credential(tenant_id: str) -> tuple[LLMKey, str]:
    """Resolve active embedding credential → (key, model_name)."""
    return resolve_embedding_credential_sync(tenant_id)


def resolve_embedding_credential_sync(tenant_id: str) -> tuple[LLMKey, str]:
    """Sync resolve for embed_text (DB I/O only)."""
    for row in _fetch_tenant_rows(tenant_id):
        if not is_embedding_purpose(str(row.provider)):
            continue
        model = _primary_model(row.allowed_models)
        if not model:
            continue
        key = _row_to_key(row)
        if not key.base_url:
            raise NexusAIException(
                _LLM_KEY_MISSING, "tenant_embedding_base_url_missing"
            )
        return key, model
    raise NexusAIException(_LLM_KEY_MISSING, "tenant_embedding_key_missing")
