"""S1–S5 hang-wait security gates (Wave E1).

拍板 08-14：sensitive 不扩 CapabilityKind；由 tenant_id / permission 推导（2A）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from backend.core.org.scope import OrgScope
from packages.auth.models import TenantContext
from packages.capability.models import CapabilitySpec

RequestableMode = Literal["true", "sensitive", "false"]

# 密钥 / 治理类 permission → 强制 sensitive（2A）
_SENSITIVE_PERM_PREFIXES = (
    "admin:",
    "admin.*",
)
_SENSITIVE_PERM_EXACT = frozenset(
    {
        "admin:llm_key",
        "admin:approve",
        "admin:*",
    }
)
_SENSITIVE_PERM_SUBSTR = (
    "api_key",
    "secret",
    "credential",
    "llm_key",
)


class HangGateError(ValueError):
    """Hang path denied — runner must fail-closed (no suspend)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def normalize_requestable(raw: Any) -> RequestableMode:
    """Compat: bool True/False → true/false; default true."""
    if raw is True or raw == "true" or raw == "True":
        return "true"
    if raw is False or raw == "false" or raw == "False":
        return "false"
    if raw == "sensitive":
        return "sensitive"
    if raw is None or raw == "":
        return "true"
    raise HangGateError("S2_BAD_REQUESTABLE", f"invalid requestable={raw!r}")


def infer_sensitive_capability(
    spec: CapabilitySpec,
    *,
    acting_tenant_id: str,
) -> bool:
    """2A: tenant_id 非本租户/非 * → sensitive；permission 含 admin/密钥类 → sensitive."""
    tid = (spec.tenant_id or "*").strip()
    if tid not in ("*", "", acting_tenant_id):
        return True
    perm = (spec.permission or "").strip().lower()
    if not perm:
        return False
    if perm in {p.lower() for p in _SENSITIVE_PERM_EXACT}:
        return True
    if perm.startswith("admin:"):
        return True
    for s in _SENSITIVE_PERM_SUBSTR:
        if s in perm:
            return True
    return False


def effective_requestable(
    node_requestable: Any,
    spec: CapabilitySpec | None,
    *,
    acting_tenant_id: str,
) -> RequestableMode:
    """Node 显式 false 尊重；否则 capability 强制 sensitive 可升格 true→sensitive."""
    mode = normalize_requestable(node_requestable)
    if mode == "false":
        return "false"
    if spec is not None and infer_sensitive_capability(
        spec, acting_tenant_id=acting_tenant_id
    ):
        return "sensitive"
    return mode


def resolve_acting_user(
    tenant: TenantContext,
    *,
    body_acting_user_id: str | None = None,
) -> str:
    """S1: acting_user 只来自已校验上下文；禁 body 覆盖。"""
    if body_acting_user_id is not None and str(body_acting_user_id).strip():
        claimed = str(body_acting_user_id).strip()
        canonical = (tenant.acting_user_id or tenant.user_id or "").strip()
        if claimed != canonical:
            raise HangGateError(
                "S1_ACTING_USER_OVERRIDE",
                "body must not override acting_user",
            )
    uid = (tenant.acting_user_id or tenant.user_id or "").strip()
    if not uid:
        raise HangGateError("S1_NO_ACTING_USER", "acting_user missing")
    return uid


def assert_no_browser_delegation(payload: dict[str, Any] | None) -> None:
    """S4: 浏览器不得下发 connector/delegation 凭证。"""
    if not payload:
        return
    forbidden = ("delegation", "delegation_id", "connector_token", "grant_token")
    for k in forbidden:
        if k in payload and payload[k] is not None:
            raise HangGateError(
                "S4_BROWSER_DELEGATION",
                f"client must not send {k}",
            )


def assert_org_scope_realtime(org_scope: OrgScope | None) -> OrgScope:
    """S3/S5: 挂起/审批必须持有实时 OrgScope（禁止 TTL 快照放行）。"""
    if org_scope is None:
        raise HangGateError("S5_NO_ORG_SCOPE", "org_scope required (realtime resolve)")
    if not isinstance(org_scope, OrgScope):
        raise HangGateError("S5_BAD_ORG_SCOPE", "org_scope must be OrgScope instance")
    return org_scope


@dataclass(frozen=True)
class HangGateResult:
    allowed: bool
    requestable: RequestableMode
    reason: str = ""


def assert_hang_wait_allowed(
    *,
    tenant: TenantContext,
    org_scope: OrgScope | None,
    node_requestable: Any,
    capability: CapabilitySpec | None,
    body_acting_user_id: str | None = None,
    client_payload: dict[str, Any] | None = None,
) -> HangGateResult:
    """
    全部 S* 过才允许进入 suspend。
    失败抛 HangGateError → runner 走 failed（不上挂起）。
    """
    resolve_acting_user(tenant, body_acting_user_id=body_acting_user_id)
    assert_no_browser_delegation(client_payload)
    assert_org_scope_realtime(org_scope)

    mode = effective_requestable(
        node_requestable,
        capability,
        acting_tenant_id=tenant.tenant_id,
    )
    if mode == "false":
        raise HangGateError(
            "S2_NOT_REQUESTABLE",
            "requestable=false — fail closed",
        )
    return HangGateResult(allowed=True, requestable=mode)
