"""请求作用域 — 租户内 user_id 绑定，防 IDOR。"""

from __future__ import annotations

from fastapi import HTTPException

from backend.core.auth.models import TenantContext


def can_access_user(tenant: TenantContext, target_user_id: str) -> bool:
    """调用方是否可操作 ``target_user_id`` 的资源。"""
    if not target_user_id:
        return False
    if target_user_id == tenant.user_id:
        return True
    if tenant.is_cross_tenant or tenant.role in ("tenant_admin", "super_admin"):
        return True
    if tenant.has_permission("admin:*"):
        return True
    return False


def assert_user_access(tenant: TenantContext, target_user_id: str) -> str:
    """校验通过则返回规范化 user_id；否则 403 AUTH_004。"""
    uid = (target_user_id or "").strip()
    if not can_access_user(tenant, uid):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "AUTH_004",
                "message": "user_scope_denied",
                "hint": "path_user_id_must_match_caller_or_admin",
            },
        )
    return uid


def require_tenant_admin(tenant: TenantContext) -> TenantContext:
    """破坏性运维（遗忘权 / 清全站缓存等）。"""
    if tenant.role not in ("tenant_admin", "super_admin"):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "AUTH_002",
                "message": "insufficient_permissions",
                "hint": "requires_tenant_admin_or_super_admin",
            },
        )
    return tenant
