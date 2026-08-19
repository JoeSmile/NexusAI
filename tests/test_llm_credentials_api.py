"""Task 49 Task 3 — Admin LLM keys + public available-models API."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.auth.models import TenantContext
from backend.routers import admin as admin_mod
from backend.routers.admin import router as admin_router
from backend.routers.llm_public import router as llm_public_router


class _StoreSession:
    """In-memory stub for llm_api_keys CRUD in admin tests."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self._next_id = 1

    def commit(self) -> None:
        return None

    def execute(self, sql: Any, params: dict[str, Any] | None = None):
        params = params or {}
        s = str(sql).lower()
        result = MagicMock()

        if "insert into llm_api_keys" in s:
            row_id = self._next_id
            self._next_id += 1
            allowed_raw = params.get("models", "[]")
            allowed = (
                json.loads(allowed_raw)
                if isinstance(allowed_raw, str)
                else allowed_raw
            )
            self.rows.append(
                {
                    "id": row_id,
                    "tenant_id": params["tid"],
                    "key_alias": params["alias"],
                    "provider": params["prov"],
                    "base_url": params["url"],
                    "encrypted_key": params["enc"],
                    "allowed_models": allowed,
                    "owner_user_id": None,
                    "key_version": 1,
                    "is_active": True,
                    "expires_at": datetime(2027, 1, 1),
                    "last_verified_ok": None,
                    "description": params.get("desc", ""),
                    "created_at": datetime(2026, 8, 16),
                    "rotated_at": None,
                }
            )
            result.fetchone.return_value = SimpleNamespace(
                id=row_id, created_at=datetime(2026, 8, 16)
            )
            return result

        if "select id, provider, allowed_models from llm_api_keys" in s:
            exclude_id = params.get("exclude_id")
            filtered = [
                r
                for r in self.rows
                if r["tenant_id"] == params.get("tid")
                and r["is_active"]
                and r["owner_user_id"] is None
                and (exclude_id is None or r["id"] != exclude_id)
            ]
            result.fetchall.return_value = [SimpleNamespace(**r) for r in filtered]
            return result

        if "select id from llm_api_keys" in s and "is_active" in s:
            exclude_id = params.get("exclude_id")
            dupes = [
                r
                for r in self.rows
                if r["tenant_id"] == params.get("tid")
                and r["provider"] == params.get("prov")
                and r["is_active"]
                and r["owner_user_id"] is None
                and (exclude_id is None or r["id"] != exclude_id)
            ]
            result.fetchone.return_value = (
                SimpleNamespace(id=dupes[0]["id"]) if dupes else None
            )
            return result

        if "select id, tenant_id, provider, is_active" in s:
            row = next((r for r in self.rows if r["id"] == params.get("id")), None)
            if row is None:
                result.fetchone.return_value = None
            elif params.get("cross") or row["tenant_id"] == params.get("tid"):
                result.fetchone.return_value = SimpleNamespace(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    provider=row["provider"],
                    is_active=row["is_active"],
                    allowed_models=row.get("allowed_models"),
                )
            else:
                result.fetchone.return_value = None
            return result

        if "update llm_api_keys set" in s:
            for row in self.rows:
                if row["id"] == params.get("id"):
                    if "models" in params:
                        raw = params["models"]
                        row["allowed_models"] = (
                            json.loads(raw) if isinstance(raw, str) else raw
                        )
                    if "url" in params:
                        row["base_url"] = params["url"]
                    if "enc" in params:
                        row["encrypted_key"] = params["enc"]
                    if "active" in params:
                        row["is_active"] = params["active"]
                    if "alias" in params:
                        row["key_alias"] = params["alias"]
            result.fetchone.return_value = None
            return result

        if "from llm_api_keys" in s and "select" in s:
            tid = params.get("tid")
            filtered = self.rows if tid is None else [
                r for r in self.rows if r["tenant_id"] == tid
            ]
            result.fetchall.return_value = [
                SimpleNamespace(**r) for r in filtered
            ]
            return result

        result.fetchone.return_value = None
        result.fetchall.return_value = []
        return result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


@pytest.fixture
def store_session() -> _StoreSession:
    return _StoreSession()


@pytest.fixture
def admin_client(monkeypatch, store_session: _StoreSession):
    app = FastAPI()
    app.include_router(admin_router, prefix="/api")

    async def _admin() -> TenantContext:
        return TenantContext("acme", "admin1", "tenant_admin", [], False)

    app.dependency_overrides[verify_human_or_legacy_key] = _admin

    km = MagicMock()
    km.encrypt.side_effect = lambda p: f"enc-{p}"
    km.decrypt.side_effect = lambda enc: (
        enc[4:] if isinstance(enc, str) and enc.startswith("enc-") else "sk-abcdefghijklmnop"
    )
    monkeypatch.setattr(
        "backend.core.key_manager.KeyManager",
        lambda *a, **k: km,
    )

    factory = MagicMock()
    factory.Session.return_value = store_session
    monkeypatch.setattr(admin_mod, "get_pg_session", lambda: factory)

    client = TestClient(app)
    client._store = store_session  # type: ignore[attr-defined]
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client(monkeypatch):
    app = FastAPI()
    app.include_router(llm_public_router, prefix="/api")

    async def _user() -> TenantContext:
        return TenantContext("acme", "u1", "user", [], False)

    app.dependency_overrides[verify_human_or_legacy_key] = _user

    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None
    session.execute.return_value.fetchall.return_value = []
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(
        "backend.core.llm_credentials.get_pg_session",
        lambda: factory,
    )

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_available_models_empty(auth_client):
    r = auth_client.get("/api/llm/available-models")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_create_llm_key_requires_models(admin_client):
    r = admin_client.post(
        "/api/admin/llm-keys",
        json={
            "key_alias": "ds1",
            "provider": "chat",
            "api_key_plaintext": "sk-test",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
        },
    )
    assert r.status_code == 200, r.text
    listed = admin_client.get("/api/admin/llm-keys").json()
    assert any(row.get("model") == "deepseek-v4-flash" for row in listed)


def test_create_rejects_empty_allowed_models(admin_client):
    r = admin_client.post(
        "/api/admin/llm-keys",
        json={
            "key_alias": "ds1",
            "provider": "chat",
            "api_key_plaintext": "sk-test",
            "base_url": "https://api.example.com/v1",
            "allowed_models": [],
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "REQ_001"


def test_create_requires_base_url(admin_client):
    r = admin_client.post(
        "/api/admin/llm-keys",
        json={
            "key_alias": "ds1",
            "provider": "chat",
            "api_key_plaintext": "sk-test",
            "base_url": "   ",
            "model": "deepseek-v4-flash",
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"]["message"] == "base_url_required"


def test_create_allows_multiple_chat_keys_different_models(admin_client):
    r1 = admin_client.post(
        "/api/admin/llm-keys",
        json={
            "key_alias": "ds1",
            "provider": "chat",
            "api_key_plaintext": "sk-test",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
        },
    )
    assert r1.status_code == 200
    r2 = admin_client.post(
        "/api/admin/llm-keys",
        json={
            "key_alias": "ds2",
            "provider": "chat",
            "api_key_plaintext": "sk-test2",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
        },
    )
    assert r2.status_code == 200, r2.text


def test_create_duplicate_model_409(admin_client):
    admin_client.post(
        "/api/admin/llm-keys",
        json={
            "key_alias": "ds1",
            "provider": "chat",
            "api_key_plaintext": "sk-test",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
        },
    )
    r = admin_client.post(
        "/api/admin/llm-keys",
        json={
            "key_alias": "ds2",
            "provider": "chat",
            "api_key_plaintext": "sk-test2",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "LLM_KEY_003"


def test_list_includes_allowed_models_and_owner_null(admin_client):
    admin_client.post(
        "/api/admin/llm-keys",
        json={
            "key_alias": "ds1",
            "provider": "chat",
            "api_key_plaintext": "sk-test",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
        },
    )
    listed = admin_client.get("/api/admin/llm-keys").json()
    assert len(listed) == 1
    row = listed[0]
    assert row["allowed_models"] == ["deepseek-v4-flash"]
    assert row["model"] == "deepseek-v4-flash"
    assert row["purpose"] == "chat"
    assert row["owner_user_id"] is None
    assert row["key_preview"] == "s***t"
    assert "api_key_plaintext" not in row
    assert "encrypted_key" not in row


def test_patch_model(admin_client):
    admin_client.post(
        "/api/admin/llm-keys",
        json={
            "key_alias": "ds1",
            "provider": "chat",
            "api_key_plaintext": "sk-test",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
        },
    )
    key_id = admin_client._store.rows[0]["id"]  # type: ignore[attr-defined]
    r = admin_client.patch(
        f"/api/admin/llm-keys/{key_id}",
        json={"model": "deepseek-chat"},
    )
    assert r.status_code == 200, r.text
    listed = admin_client.get("/api/admin/llm-keys").json()
    assert listed[0]["model"] == "deepseek-chat"


def test_available_models_returns_configured(auth_client, monkeypatch):
    row = SimpleNamespace(
        provider="chat",
        allowed_models=["deepseek-v4-flash"],
        base_url="https://api.deepseek.com/v1",
        id=1,
        tenant_id="acme",
        encrypted_key="x",
        key_version=1,
        is_active=True,
        expires_at=None,
    )
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None
    session.execute.return_value.fetchall.return_value = [row]
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(
        "backend.core.llm_credentials.get_pg_session",
        lambda: factory,
    )

    r = auth_client.get("/api/llm/available-models")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0] == {
        "model": "deepseek-v4-flash",
        "series": "chat",
        "configured": True,
    }


def test_available_models_skips_embedding(auth_client, monkeypatch):
    rows = [
        SimpleNamespace(
            provider="embedding",
            allowed_models=["text-embedding-3-small"],
            base_url="https://api.openai.com/v1",
            id=1,
            tenant_id="acme",
            encrypted_key="x",
            key_version=1,
            is_active=True,
            expires_at=None,
        ),
        SimpleNamespace(
            provider="chat",
            allowed_models=["gpt-4o-mini"],
            base_url="https://api.openai.com/v1",
            id=2,
            tenant_id="acme",
            encrypted_key="y",
            key_version=1,
            is_active=True,
            expires_at=None,
        ),
    ]
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None
    session.execute.return_value.fetchall.return_value = rows
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(
        "backend.core.llm_credentials.get_pg_session",
        lambda: factory,
    )

    r = auth_client.get("/api/llm/available-models")
    assert r.status_code == 200
    assert r.json()["items"] == [
        {"model": "gpt-4o-mini", "series": "chat", "configured": True}
    ]
