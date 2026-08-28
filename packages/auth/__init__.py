"""认证包 — API Key / RBAC / 请求签名"""

from packages.auth.api_key_auth import optional_api_key, verify_api_key
from packages.auth.models import ROLES, TenantContext
from packages.auth.permissions import (
    cross_tenant_only,
    require_any_permission,
    require_permission,
)
from packages.auth.scope import (
    assert_user_access,
    can_access_user,
    require_tenant_admin,
    resolve_acting_user_id,
)
from packages.auth.signature_auth import SignatureMiddleware, sign_request

__all__ = [
    "ROLES",
    "SignatureMiddleware",
    "TenantContext",
    "assert_user_access",
    "can_access_user",
    "cross_tenant_only",
    "optional_api_key",
    "require_any_permission",
    "require_permission",
    "require_tenant_admin",
    "resolve_acting_user_id",
    "sign_request",
    "verify_api_key",
]
