"""Wave C2 — visible vs permitted save path."""

from __future__ import annotations

from packages.auth.models import TenantContext
from packages.capability.models import (
    CapabilityKind,
    CapabilityProvider,
    CapabilitySpec,
    CapabilityStatus,
)
from packages.capability.invoke import capability_visible_to
from backend.core.workflow.service import capability_catalog_visible


def test_catalog_visible_ignores_permission() -> None:
    tenant = TenantContext("t1", "u1", "user", [], False)
    spec = CapabilitySpec(
        id="x",
        name="X",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        spec={"governance": True},
        permission="admin:*",
        status=CapabilityStatus.ENABLED,
        tenant_id="*",
    )
    assert capability_catalog_visible(spec, tenant) is True
    # invoke 可见性仍绑 permission — 保存路径故意不共用
    assert capability_visible_to(spec, tenant) is False


def test_other_tenant_not_catalog_visible() -> None:
    tenant = TenantContext("t1", "u1", "user", [], False)
    spec = CapabilitySpec(
        id="x",
        name="X",
        kind=CapabilityKind.TOOL,
        provider=CapabilityProvider.NEXUSAI,
        spec={"governance": True},
        permission="chat:write",
        tenant_id="t2",
    )
    assert capability_catalog_visible(spec, tenant) is False
