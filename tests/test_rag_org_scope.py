"""Wave B3 — RAG org tag + query visibility."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from packages.auth.models import TenantContext
from backend.core.org.models import OrgUnitDTO
from backend.core.org.scope import OrgScope
from backend.modules.rag.org_tag import chunk_visible_to_scope, require_primary_org_for_ingest


def test_null_chunk_only_governance():
    admin = OrgScope(
        tenant_id="acme",
        user_id="a",
        platform_role="tenant_admin",
        primary_org_unit_id=None,
        org_unit_ids=frozenset(),
        subtree_paths=frozenset(),
        business_roles=frozenset(),
    )
    member = OrgScope(
        tenant_id="acme",
        user_id="u",
        platform_role="user",
        primary_org_unit_id="fin",
        org_unit_ids=frozenset({"fin"}),
        subtree_paths=frozenset(),
        business_roles=frozenset({"member"}),
    )
    assert chunk_visible_to_scope(admin, org_unit_id=None) is True
    assert chunk_visible_to_scope(member, org_unit_id=None) is False
    assert chunk_visible_to_scope(member, org_unit_id="fin") is True
    assert chunk_visible_to_scope(member, org_unit_id="hr") is False


def test_manager_subtree_chunk():
    mgr = OrgScope(
        tenant_id="acme",
        user_id="m",
        platform_role="user",
        primary_org_unit_id="fin",
        org_unit_ids=frozenset({"fin"}),
        subtree_paths=frozenset({"/fin/"}),
        business_roles=frozenset({"dept_manager"}),
    )
    assert (
        chunk_visible_to_scope(mgr, org_unit_id="acct", unit_path="/fin/acct/")
        is True
    )
    assert chunk_visible_to_scope(mgr, org_unit_id="hr", unit_path="/hr/") is False


def test_require_primary_org_400(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(
        "backend.modules.rag.org_tag.resolve_org_scope",
        lambda *a, **k: OrgScope(
            tenant_id="acme",
            user_id="u",
            platform_role="user",
            primary_org_unit_id=None,
            org_unit_ids=frozenset(),
            subtree_paths=frozenset(),
            business_roles=frozenset(),
        ),
    )
    tenant = TenantContext("acme", "u", "user", [], False)
    with pytest.raises(HTTPException) as ei:
        require_primary_org_for_ingest(session, tenant)
    assert ei.value.status_code == 400
    assert ei.value.detail["code"] == "RAG_ORG_001"


def test_require_primary_org_ok(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(
        "backend.modules.rag.org_tag.resolve_org_scope",
        lambda *a, **k: OrgScope(
            tenant_id="acme",
            user_id="u",
            platform_role="user",
            primary_org_unit_id="fin",
            org_unit_ids=frozenset({"fin"}),
            subtree_paths=frozenset(),
            business_roles=frozenset({"member"}),
        ),
    )
    monkeypatch.setattr(
        "backend.core.org.service.get_unit",
        lambda *a, **k: OrgUnitDTO(
            id="fin",
            tenant_id="acme",
            parent_id=None,
            name="财务",
            path="/fin/",
            deleted_at=None,
            created_at=datetime(2026, 8, 1),
        ),
    )
    tenant = TenantContext("acme", "u", "user", [], False)
    oid, scope = require_primary_org_for_ingest(session, tenant)
    assert oid == "fin"
    assert scope.primary_org_unit_id == "fin"
