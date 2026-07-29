"""权限装饰器 — 返回 FastAPI Depends 函数"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from backend.core.auth.api_key_auth import verify_api_key
from backend.core.auth.models import TenantContext


def require_permission(permission: str):
    """
    权限检查 Depends 工厂。

    用法:
        @router.post("/chat")
        async def chat(tenant: TenantContext = Depends(require_permission("chat:write"))):
            ...
    """

    async def _check(
        request: Request,
        tenant: TenantContext = Depends(verify_api_key),
    ) -> TenantContext:
        if not tenant.has_permission(permission):
            raise HTTPException(
                status_code=403,
                detail={"code": "AUTH_002", "message": "insufficient_permissions"},
            )
        request.state.tenant_context = tenant
        return tenant

    return _check


def cross_tenant_only():
    """仅 super_admin 可访问"""

    async def _check(
        request: Request,
        tenant: TenantContext = Depends(verify_api_key),
    ) -> TenantContext:
        if not tenant.is_cross_tenant:
            raise HTTPException(
                status_code=403,
                detail={"code": "AUTH_003", "message": "cross_tenant_access_denied"},
            )
        request.state.tenant_context = tenant
        return tenant

    return _check


def require_any_permission(permissions: list[str]):
    """满足任意一个权限即可通过"""

    async def _check(
        request: Request,
        tenant: TenantContext = Depends(verify_api_key),
    ) -> TenantContext:
        for perm in permissions:
            if tenant.has_permission(perm):
                request.state.tenant_context = tenant
                return tenant
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_002", "message": "insufficient_permissions"},
        )

    return _check
