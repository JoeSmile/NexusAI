"""Task 55 slice 3 — terms versions + acceptance gate."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routers.terms import router as terms_router
from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from packages.errors import NexusAIException
from packages.terms import service as terms_mod
from packages.terms.service import (
    enforce_terms_for_chat,
    get_current_terms,
    list_pending_terms,
    record_acceptance,
    required_terms_kinds,
)


@pytest.fixture
def user() -> TenantContext:
    return TenantContext("acme", "u1", "user", [], False)


def test_required_terms_kinds_is_single_user_agreement() -> None:
    assert required_terms_kinds("company") == ["user_agreement"]
    assert required_terms_kinds("byok") == ["user_agreement"]


def test_get_current_terms_after_migration() -> None:
    doc = get_current_terms("user_agreement")
    assert doc is not None
    assert doc["version"] == "v1.0.0"
    assert "用户协议" in doc["content_md"]
    assert "正式法律文本将由运营补充" in doc["content_md"]
    # Legacy kinds remain readable for old /terms?kind= links.
    privacy = get_current_terms("privacy")
    assert privacy is not None
    assert "[律师审]" in privacy["content_md"]


def test_record_and_clear_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    tid = f"tt_{uuid.uuid4().hex[:8]}"
    uid = f"u_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("TERMS_ENFORCEMENT_ENABLED", "1")

    pending_before = list_pending_terms(tenant_id=tid, user_id=uid)
    assert len(pending_before) == 1
    assert pending_before[0]["kind"] == "user_agreement"

    for doc in pending_before:
        record_acceptance(
            tenant_id=tid,
            user_id=uid,
            kind=doc["kind"],
            version=doc["version"],
            ip_address="127.0.0.1",
        )

    assert list_pending_terms(tenant_id=tid, user_id=uid) == []
    enforce_terms_for_chat(tenant_id=tid, user_id=uid)


def test_enforce_raises_when_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERMS_ENFORCEMENT_ENABLED", "1")
    with pytest.raises(NexusAIException) as exc:
        enforce_terms_for_chat(tenant_id="new_tenant", user_id="new_user")
    assert exc.value.code == "TERMS_001"


def test_terms_current_api_public() -> None:
    app = FastAPI()
    app.include_router(terms_router, prefix="/api")
    r = TestClient(app).get("/api/terms/current?kind=user_agreement")
    assert r.status_code == 200
    assert r.json()["kind"] == "user_agreement"


def test_terms_pending_api(user: TenantContext) -> None:
    app = FastAPI()
    app.include_router(terms_router, prefix="/api")

    async def _auth() -> TenantContext:
        return user

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    r = TestClient(app).get("/api/terms/pending")
    assert r.status_code == 200
    assert "pending" in r.json()


def test_terms_accept_api(user: TenantContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        terms_mod,
        "record_acceptance",
        lambda **kw: {"ok": True, **kw},
    )
    app = FastAPI()
    app.include_router(terms_router, prefix="/api")

    async def _auth() -> TenantContext:
        return user

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    r = TestClient(app).post(
        "/api/terms/accept",
        json={"kind": "privacy", "version": "v1.0.0"},
    )
    assert r.status_code == 200
