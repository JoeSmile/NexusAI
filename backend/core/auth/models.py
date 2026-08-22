"""认证 + 权限数据模型"""

from __future__ import annotations

from dataclasses import dataclass

# ── 角色权限映射 ────────────────────────────────
# super_admin: 所有权限
# auditor: 跨租户只读审计
# tenant_admin: 本租户管理
# user: 应用级权限挂载
ROLES: dict[str, dict] = {
    "super_admin": {
        "description": "跨租户管理员",
        "permissions": [
            "admin:*",
            "audit:read",
            "audit:export",
        ],
    },
    "auditor": {
        "description": "跨租户审计员",
        "permissions": [
            "audit:read",
            "audit:export",
        ],
    },
    "tenant_admin": {
        "description": "租户管理员",
        "permissions": [
            "chat:*",
            "multimodal:vision",
            "kb:*",
            "admin:approve",
            "admin:llm_key",
        ],
    },
    "user": {
        "description": "普通用户",
        "permissions": [
            "chat:write",
            "chat:read",
        ],
    },
}


def _perm_matches(granted: str, needed: str) -> bool:
    """单条权限匹配 — 支持 `resource:*` 通配符。"""
    if granted == "admin:*":
        return True
    if granted == needed:
        return True
    if granted.endswith(":*"):
        resource = granted.split(":", 1)[0]
        return needed == resource or needed.startswith(f"{resource}:")
    return False


@dataclass
class TenantContext:
    """认证上下文 — 请求经过 auth 后注入"""

    tenant_id: str
    user_id: str
    role: str
    extra_permissions: list[str]
    is_cross_tenant: bool
    # Wave A scaffold — transitional kind "api_key"; 2B → machine_key
    credential_kind: str = "api_key"
    key_id: str | None = None
    acting_user_id: str | None = None
    # Wave B — business roles from org memberships (optional; filled by callers)
    business_roles: list[str] | None = None

    def has_permission(self, permission: str, *, org_scope: object | None = None) -> bool:
        """平台 ∪ extra ∪ 业务角色 — 委托 evaluate_permission（Wave B）。"""
        from backend.core.auth.evaluator import evaluate_permission
        from backend.core.org.scope import OrgScope

        scope = org_scope if isinstance(org_scope, OrgScope) else None
        return evaluate_permission(
            platform_role=self.role,
            extra_permissions=self.extra_permissions,
            business_roles=self.business_roles or [],
            needed=permission,
            org_scope=scope,
        )