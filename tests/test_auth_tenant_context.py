"""Wave A A1 — TenantContext scaffold fields from verify_api_key (L2)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.core.auth import api_key_auth as auth_mod
from backend.core.auth.models import TenantContext


@pytest.mark.asyncio
async def test_verify_api_key_fills_scaffold_fields(monkeypatch) -> None:
    row = SimpleNamespace(
        id=42,
        tenant_id="acme",
        user_id="alice",
        role="user",
        extra_permissions=[],
    )
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None
    session.execute.return_value.fetchone.return_value = row
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(
        "backend.database.pgvector_session.get_pg_session",
        lambda: factory,
    )

    ctx = await auth_mod.verify_api_key("cg_test_key_value")
    assert isinstance(ctx, TenantContext)
    assert ctx.tenant_id == "acme"
    assert ctx.user_id == "alice"
    assert ctx.role == "user"
    assert ctx.credential_kind == "api_key"
    assert ctx.key_id == "42"
    assert ctx.acting_user_id == "alice"
    assert ctx.is_cross_tenant is False


@pytest.mark.asyncio
async def test_verify_api_key_defaults_on_positional_tenant_context() -> None:
    """Existing positional constructors still get scaffold defaults."""
    ctx = TenantContext("t1", "u1", "user", [], False)
    assert ctx.credential_kind == "api_key"
    assert ctx.key_id is None
    assert ctx.acting_user_id is None


@pytest.mark.asyncio
async def test_verify_api_key_missing_raises_401() -> None:
    with pytest.raises(HTTPException) as ei:
        await auth_mod.verify_api_key(None)
    assert ei.value.status_code == 401
