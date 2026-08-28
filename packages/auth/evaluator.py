"""Permission evaluator — platform ∪ extra ∪ business roles (Wave B2)."""

from __future__ import annotations

from collections.abc import Iterable

from packages.org.scope import OrgScope
from packages.auth.models import ROLES, _perm_matches


def evaluate_permission(
    *,
    platform_role: str,
    extra_permissions: list[str],
    business_roles: Iterable[str],
    needed: str,
    org_scope: OrgScope | None,
) -> bool:
    """
    Actionability check (可调). Visibility stays in capability_visible_to / OrgScope lists.

    Rules (v1):
    - Platform ROLES + extra_permissions (unchanged wildcards)
    - dept_manager → workflow:approve_dept only when org_scope present (caller enforces resource in scope)
    - member → no approve
    - unknown business roles ignored
    - Never elevate platform role via business roles
    """
    for rp in extra_permissions or []:
        if _perm_matches(rp, needed):
            return True
    role_perms = ROLES.get(platform_role, {}).get("permissions", [])
    for rp in role_perms:
        if _perm_matches(rp, needed):
            return True

    roles = frozenset(business_roles or [])
    if needed == "workflow:approve_dept":
        if "dept_manager" not in roles:
            return False
        # Require a resolved scope object (resource check is caller's assert_org_access)
        return org_scope is not None

    return False
