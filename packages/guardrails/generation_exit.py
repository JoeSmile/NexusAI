"""生成出口共用护栏：G7 学员脱敏 + 教培营销红线 + 按 profile 的角色漂移。

产品默认 ``content_factory``（口播话术不拦「家人们/直播间」）。
企业秘书租户 opt-in：``tenant_config.config.output_guard_profile = "secretary"``。
``check_output`` 自身默认 secretary，只服务它的单测；产品四出口走本模块解析。
"""

from __future__ import annotations

import logging
from typing import Any

from packages.guardrails.base import GuardResult
from packages.guardrails.edu_marketing import apply_edu_marketing_redlines
from packages.guardrails.output_guard import check_output

logger = logging.getLogger(__name__)

PROFILE_SECRETARY = "secretary"
PROFILE_CONTENT_FACTORY = "content_factory"
DEFAULT_OUTPUT_GUARD_PROFILE = PROFILE_CONTENT_FACTORY
VALID_PROFILES = frozenset({PROFILE_SECRETARY, PROFILE_CONTENT_FACTORY})


def _read_tenant_guard_profile(tenant_id: str) -> str | None:
    if not tenant_id:
        return None
    try:
        from packages.database.pgvector_session import TenantConfig, get_pg_session

        pg = get_pg_session()
        with pg.get_session() as session:
            row = (
                session.query(TenantConfig)
                .filter(TenantConfig.tenant_id == tenant_id)
                .one_or_none()
            )
            if row is None or not isinstance(row.config, dict):
                return None
            raw = row.config.get("output_guard_profile")
            if isinstance(raw, str) and raw.strip() in VALID_PROFILES:
                return raw.strip()
    except Exception:
        logger.debug("output_guard_profile lookup skipped", exc_info=True)
    return None


def resolve_output_guard_profile(tenant_id: str) -> str:
    raw = _read_tenant_guard_profile(tenant_id)
    if raw in VALID_PROFILES:
        return raw
    return DEFAULT_OUTPUT_GUARD_PROFILE


async def sanitize_generation_exit(
    text: str,
    *,
    tenant_id: str = "",
    profile: str | None = None,
    warm: dict[str, Any] | None = None,
    names: list[str] | None = None,
    apply_length_limit: bool = True,
) -> GuardResult:
    """四出口共用：脱敏 + 红线替换 + check_output。红线 fail-open，密钥/人设仍可 BLOCK。"""
    body = text or ""
    reasons: list[str] = []

    try:
        from packages.memory.memory_service import redact_student_names_in_text

        before = body
        body = redact_student_names_in_text(
            body,
            tenant_id=tenant_id or "",
            names=names,
            warm=warm,
        )
        if body != before:
            reasons.append("g7_student_pii")
    except Exception:
        logger.debug("generation_exit G7 skipped", exc_info=True)

    try:
        body, hits = apply_edu_marketing_redlines(body)
        if hits:
            reasons.extend(f"edu_marketing:{h}" for h in hits)
    except Exception:
        logger.debug("generation_exit marketing skipped", exc_info=True)
        hits = []

    resolved = (
        profile if profile in VALID_PROFILES else resolve_output_guard_profile(tenant_id)
    )
    max_chars = 4000 if apply_length_limit else None
    out = await check_output(body, profile=resolved, max_chars=max_chars)
    if out.action == "blocked":
        return out

    extra = [out.reason] if out.reason else []
    merged = ";".join([*reasons, *extra])
    action = out.action
    if hits and action == "pass":
        action = "redacted"
    return GuardResult(
        action=action,
        redacted_text=out.redacted_text,
        reason=merged,
    )
