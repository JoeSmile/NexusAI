"""认证模块测试"""

from backend.core.auth.models import ROLES, TenantContext


def test_super_admin_permissions():
    """super_admin 应有所有权限（admin:*）"""
    admin = TenantContext("t1", "admin", "super_admin", [], True)
    assert admin.has_permission("audit:read")
    assert admin.has_permission("audit:export")
    assert admin.has_permission("admin:approve")
    assert admin.has_permission("chat:write")


def test_user_limited_permissions():
    """普通用户默认只有 chat 权限"""
    user = TenantContext("t1", "user1", "user", [], False)
    assert user.has_permission("chat:write")
    assert user.has_permission("chat:read")
    assert not user.has_permission("audit:read")
    assert not user.has_permission("admin:approve")


def test_role_permissions():
    """角色默认权限"""
    user = TenantContext("t1", "u1", "user", [], False)
    assert user.has_permission("chat:write")
    assert not user.has_permission("audit:read")


def test_wildcard_permissions():
    """通配符权限（extra_permissions）"""
    editor = TenantContext("t1", "u3", "unknown_role", ["kb:*"], False)
    assert editor.has_permission("kb:read")
    assert editor.has_permission("kb:write")
    assert not editor.has_permission("chat:write")


def test_cross_tenant():
    """跨租户标志"""
    admin = TenantContext("t1", "admin", "super_admin", [], True)
    user = TenantContext("t1", "user", "user", [], False)
    assert admin.is_cross_tenant
    assert not user.is_cross_tenant


def test_roles_defined():
    """所有角色已定义"""
    assert "super_admin" in ROLES
    assert "auditor" in ROLES
    assert "tenant_admin" in ROLES
    assert "user" in ROLES
