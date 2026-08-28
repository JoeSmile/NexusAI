"""Admin console access helpers (Task 67 slice 0)."""

from __future__ import annotations

from fastapi import Depends, HTTPException

from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext


def is_console_super_admin(tenant: TenantContext) -> bool:
    return tenant.role == "super_admin" or tenant.has_permission("admin:*")


def is_console_tenant_admin(tenant: TenantContext) -> bool:
    return tenant.role == "tenant_admin"


def can_read_console(tenant: TenantContext) -> bool:
    return is_console_super_admin(tenant) or is_console_tenant_admin(tenant)


def can_mutate_tool_status(tenant: TenantContext) -> bool:
    return is_console_super_admin(tenant)


def can_mutate_exec_policy(tenant: TenantContext) -> bool:
    return is_console_super_admin(tenant)


def can_mutate_tenant_allowlist(tenant: TenantContext) -> bool:
    return is_console_super_admin(tenant) or is_console_tenant_admin(tenant)


async def require_console_reader(
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> TenantContext:
    if not can_read_console(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_002", "message": "console_access_denied"},
        )
    return tenant


async def require_console_super_admin(
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
) -> TenantContext:
    if not is_console_super_admin(tenant):
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_002", "message": "super_admin_required"},
        )
    return tenant
