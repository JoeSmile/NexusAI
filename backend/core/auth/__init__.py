"""认证包 — API Key / RBAC / 请求签名"""

from backend.core.auth.api_key_auth import optional_api_key, verify_api_key
from backend.core.auth.models import ROLES, TenantContext
from backend.core.auth.permissions import (
    cross_tenant_only,
    require_any_permission,
    require_permission,
)
from backend.core.auth.scope import (
    assert_user_access,
    can_access_user,
    require_tenant_admin,
    resolve_acting_user_id,
)
from backend.core.auth.signature_auth import SignatureMiddleware, sign_request

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
