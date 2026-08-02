"""CapabilityRegistry — env 静态 + DB 动态双源（Task 30.02）。

加载顺序:
1. model_registry 映射为 kind=model（兼容现有调用，不破坏 ModelSpec API）
2. env `CAPABILITY_REGISTRY_JSON`（同 id 覆盖 model）
3. DB `capabilities` 表（同 id 覆盖 env/model）
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from backend.core.capability.errors import CapabilityNotFoundError
from backend.core.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
    CapabilityStatus,
)

logger = logging.getLogger(__name__)

_REGISTRY: CapabilityRegistry | None = None


def _provider_from_str(raw: str) -> CapabilityProvider:
    try:
        return CapabilityProvider(raw)
    except ValueError:
        # model_registry 可能是 deepseek/openai/mock 等 → 归到 contextgate 或 self-hosted
        if raw in ("vllm", "local", "mock"):
            return CapabilityProvider.SELF_HOSTED
        return CapabilityProvider.CONTEXTGATE


def _status_from_enabled(enabled: bool) -> CapabilityStatus:
    return CapabilityStatus.ENABLED if enabled else CapabilityStatus.DISABLED


def model_spec_to_capability(model: Any) -> CapabilitySpec:
    """将 ModelSpec 映射为 kind=model 的 CapabilitySpec（只读兼容层）。"""
    return CapabilitySpec(
        id=f"model:{model.name}",
        name=model.name,
        kind=CapabilityKind.MODEL,
        provider=_provider_from_str(str(getattr(model, "provider", "contextgate"))),
        spec={
            "base_url": getattr(model, "base_url", "") or "",
            "api_key_ref": getattr(model, "api_key_ref", "") or "",
            "capability": getattr(model, "capability", "chat") or "chat",
            "max_tokens": int(getattr(model, "max_tokens", 1000) or 1000),
            "tier": getattr(model, "tier", "good") or "good",
            "extra": dict(getattr(model, "extra", {}) or {}),
        },
        status=_status_from_enabled(bool(getattr(model, "enabled", True))),
        cost_model={"cost_per_1k": float(getattr(model, "cost_per_1k", 0.0) or 0.0)},
        permission="chat:write",
        tenant_id="*",
    )


class CapabilityRegistry:
    """进程内能力注册表。"""

    def __init__(self) -> None:
        self._by_id: dict[str, CapabilitySpec] = {}

    def register(self, spec: CapabilitySpec) -> None:
        from backend.core.capability.governance import validate_governance_declaration

        validate_governance_declaration(spec)
        self._by_id[spec.id] = spec

    def get(self, capability_id: str, *, require_enabled: bool = True) -> CapabilitySpec:
        spec = self._by_id.get(capability_id)
        if spec is None:
            raise CapabilityNotFoundError(detail=capability_id)
        if require_enabled and spec.status != CapabilityStatus.ENABLED:
            from backend.core.capability.errors import CapabilityDisabledError

            raise CapabilityDisabledError(detail=capability_id)
        return spec

    def list(
        self,
        *,
        kind: CapabilityKind | str | None = None,
        provider: CapabilityProvider | str | None = None,
        include_disabled: bool = False,
    ) -> list[CapabilitySpec]:
        kind_v = CapabilityKind(kind) if isinstance(kind, str) else kind
        provider_v = (
            CapabilityProvider(provider) if isinstance(provider, str) else provider
        )
        out: list[CapabilitySpec] = []
        for spec in self._by_id.values():
            if not include_disabled and spec.status != CapabilityStatus.ENABLED:
                continue
            if kind_v is not None and spec.kind != kind_v:
                continue
            if provider_v is not None and spec.provider != provider_v:
                continue
            out.append(spec)
        return sorted(out, key=lambda s: s.id)

    def load_from_env(self, raw: str | None = None) -> int:
        """从 CAPABILITY_REGISTRY_JSON 加载；返回写入条数。"""
        if raw is None:
            text = os.getenv("CAPABILITY_REGISTRY_JSON", "").strip()
            if not text:
                try:
                    from config import get_settings

                    text = (get_settings().capability_registry_json or "").strip()
                except Exception:
                    text = ""
        else:
            text = raw.strip()
        if not text or text == "[]":
            return 0
        try:
            items = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("CAPABILITY_REGISTRY_JSON invalid JSON; skipped")
            return 0
        if not isinstance(items, list):
            logger.warning("CAPABILITY_REGISTRY_JSON must be a list; skipped")
            return 0
        n = 0
        for item in items:
            if not isinstance(item, dict) or "id" not in item or "kind" not in item:
                continue
            try:
                nested = dict(item.get("spec") or {})
                # 顶层 base_url / api_key_ref 写入 spec（config 示例扁平写法）
                if item.get("base_url") and "base_url" not in nested:
                    nested["base_url"] = item["base_url"]
                if item.get("api_key_ref") and "api_key_ref" not in nested:
                    nested["api_key_ref"] = item["api_key_ref"]
                if "governance" in item and "governance" not in nested:
                    nested["governance"] = item["governance"]
                spec = CapabilitySpec(
                    id=str(item["id"]),
                    name=str(item.get("name") or item["id"]),
                    kind=CapabilityKind(str(item["kind"])),
                    provider=CapabilityProvider(
                        str(item.get("provider", "contextgate"))
                    ),
                    spec=nested,
                    status=CapabilityStatus(str(item.get("status", "enabled"))),
                    cost_model=dict(item.get("cost_model") or {}),
                    permission=str(item.get("permission") or ""),
                    tenant_id=str(item.get("tenant_id") or "*"),
                )
                self.register(spec)
                n += 1
            except Exception as exc:
                # 含 CAP_004 治理未声明、非法 kind 等
                logger.warning("skip capability env item %s: %s", item.get("id"), exc)
        return n

    def load_from_model_registry(self) -> int:
        """兼容映射：不修改 model_registry 公共 API。"""
        from backend.core.model_registry import get_registry

        n = 0
        for model in get_registry().values():
            self.register(model_spec_to_capability(model))
            n += 1
        return n

    def load_from_db(self) -> int:
        """DB 优先：同 id 覆盖 env/model。表不存在时静默跳过。"""
        try:
            from backend.database.pgvector_session import Capability, get_pg_session
        except Exception as exc:  # pragma: no cover
            logger.debug("capability DB import skipped: %s", exc)
            return 0

        n = 0
        try:
            pg = get_pg_session()
            with pg.get_session() as session:
                rows = session.query(Capability).all()
                for row in rows:
                    try:
                        spec = CapabilitySpec(
                            id=str(row.id),
                            name=str(row.name),
                            kind=CapabilityKind(str(row.kind)),
                            provider=CapabilityProvider(str(row.provider)),
                            spec=dict(row.spec or {}),
                            status=CapabilityStatus(str(row.status or "enabled")),
                            cost_model=dict(row.cost_model or {}),
                            permission=str(row.permission or ""),
                            tenant_id=str(row.tenant_id or "*"),
                        )
                        self.register(spec)
                        n += 1
                    except Exception as exc:
                        # 含 CAP_004 治理未声明等；跳过坏行，不中断整表加载
                        logger.warning("skip capability row %s: %s", row.id, exc)
        except Exception as exc:
            # 迁移未跑 / DB 不可用时不阻断启动
            logger.info("capability DB load skipped: %s", exc)
            return 0
        return n

    def bootstrap(self) -> None:
        """完整加载：model_registry → env → DB(覆盖)。"""
        self._by_id.clear()
        model_n = self.load_from_model_registry()
        env_n = self.load_from_env()
        db_n = self.load_from_db()
        logger.info(
            "CapabilityRegistry loaded: model=%s env=%s db=%s total=%s",
            model_n,
            env_n,
            db_n,
            len(self._by_id),
        )


def get_capability_registry(*, reload: bool = False) -> CapabilityRegistry:
    global _REGISTRY
    if _REGISTRY is None or reload:
        reg = CapabilityRegistry()
        reg.bootstrap()
        _REGISTRY = reg
    return _REGISTRY


def reload_capability_registry() -> CapabilityRegistry:
    return get_capability_registry(reload=True)


def resolve_credential(
    api_key_ref: str,
    *,
    tenant_id: str = "*",
) -> str:
    """解析能力凭证：KeyManager 加密库优先，env 明文兜底。

    ``api_key_ref`` 通常是 env 名（如 ``DIFY_API_KEY``），也可对应
    ``llm_api_keys.key_alias``。无 master key / 无 DB 行时退回 ``os.getenv``。
    """
    ref = (api_key_ref or "").strip()
    if not ref:
        return ""

    # 1) KeyManager + llm_api_keys（按 key_alias）
    try:
        from sqlalchemy import text

        from backend.core.key_manager import KeyManager
        from backend.database.pgvector_session import get_pg_session

        km = KeyManager()
        pg = get_pg_session()
        with pg.get_session() as session:
            row = session.execute(
                text(
                    """
                    SELECT encrypted_key FROM llm_api_keys
                    WHERE key_alias = :alias AND is_active = true
                      AND (tenant_id = :tid OR :tid = '*' OR tenant_id = '*')
                    ORDER BY CASE WHEN tenant_id = :tid THEN 0 ELSE 1 END,
                             key_version DESC
                    LIMIT 1
                    """
                ),
                {"alias": ref, "tid": tenant_id},
            ).fetchone()
            if row and row[0]:
                return km.decrypt(str(row[0]))
    except Exception as exc:
        logger.debug("resolve_credential KeyManager path skipped: %s", exc)

    # 2) env 明文兜底
    return os.getenv(ref, "") or ""


def get_cap_quota_daily_calls() -> int:
    try:
        from config import get_settings

        return int(get_settings().cap_quota_daily_calls)
    except Exception:
        return int(os.getenv("CAP_QUOTA_DAILY_CALLS", "1000") or 1000)


def get_cap_quota_daily_cost_usd() -> float:
    try:
        from config import get_settings

        return float(get_settings().cap_quota_daily_cost_usd)
    except Exception:
        return float(os.getenv("CAP_QUOTA_DAILY_COST_USD", "10.0") or 10.0)
