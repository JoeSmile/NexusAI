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

    def has_permission(self, permission: str) -> bool:
        """权限检查 — 支持通配符 `admin:*` / `chat:*`（角色与 extra 均生效）"""
        for rp in self.extra_permissions:
            if _perm_matches(rp, permission):
                return True
        role_perms = ROLES.get(self.role, {}).get("permissions", [])
        for rp in role_perms:
            if _perm_matches(rp, permission):
                return True
        return False
