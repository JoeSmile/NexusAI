"""Task 38.03 — 账号认证路由单测。

镜像 `tests/test_ab_router.py` 的桩模式: FastAPI() + include auth router +
MagicMock session + monkeypatch `backend.routers.auth.get_pg_session`。
失败计数走进程内降级 (monkeypatch `get_sync_redis` → None),fixture 清 `_fail_fallback`。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.auth import password as pw_mod
from backend.routers import auth as auth_mod
from backend.routers.auth import router


# ── password 工具单测(无 DB) ────────────────────────────────────
class TestPasswordUtil:
    def test_hash_is_bcrypt_and_verifies(self) -> None:
        h = pw_mod.hash_password("supersecret")
        assert h.startswith("$2")
        assert pw_mod.verify_password("supersecret", h) is True
        assert pw_mod.verify_password("wrong", h) is False

    def test_verify_empty_hash_returns_false(self) -> None:
        assert pw_mod.verify_password("x", "") is False
        assert pw_mod.verify_password("x", "not-a-hash") is False


# ── 路由单测 ────────────────────────────────────────────────────
@pytest.fixture
def auth_client(monkeypatch):
    """FastAPI + auth router + 桩 session + 内存降级失败计数。"""
    app = FastAPI()
    app.include_router(router)  # router 已带 /api/auth 前缀

    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None
    session.execute.return_value.fetchone.return_value = None
    session.execute.return_value.fetchall.return_value = []
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(auth_mod, "get_pg_session", lambda: factory)

    # 失败计数走进程内降级
    monkeypatch.setattr(auth_mod, "get_sync_redis", lambda decode_responses=False: None)

    client = TestClient(app)
    client._session = session  # type: ignore[attr-defined]
    yield client

    auth_mod._fail_fallback.clear()


def _capture_insert_params(session: MagicMock) -> dict[str, dict[str, Any]]:
    """从 session.execute 调用里抓 INSERT 的参数(按表名归类)。"""
    inserts: dict[str, dict[str, Any]] = {}
    for call in session.execute.call_args_list:
        sql = call.args[0] if call.args else call.kwargs.get("sql")
        if sql is None:
            continue
        s = str(sql).lower()
        params = call.args[1] if len(call.args) > 1 else call.kwargs.get("params", {})
        if "insert into users" in s:
            inserts["users"] = params
        elif "insert into api_keys" in s:
            inserts["api_keys"] = params
    return inserts


# ── register ───────────────────────────────────────────────────
def test_register_success_returns_cg_key_and_bcrypt_hash(auth_client) -> None:
    r = auth_client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "password123", "role": "user"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_key"].startswith("cg_")
    assert body["role"] == "user"
    assert body["tenant_id"] == "acme"
    assert body["user_id"] == "alice"

    inserts = _capture_insert_params(auth_client._session)  # type: ignore[attr-defined]
    assert "users" in inserts
    assert inserts["users"]["ph"].startswith("$2")  # bcrypt 密文落库
    assert "api_keys" in inserts
    assert inserts["api_keys"]["hash"].startswith(
        "sha256$"
    ) or len(inserts["api_keys"]["hash"]) == 64  # sha256 hex


def test_register_duplicate_username_returns_409(auth_client) -> None:
    # 第一次:无 existing → 200
    auth_client.post(
        "/api/auth/register",
        json={"username": "bob", "password": "password123"},
    )
    # 第二次:SELECT 命中 existing → 409
    auth_client._session.execute.return_value.fetchone.return_value = SimpleNamespace(  # type: ignore[attr-defined]
        id=1
    )
    r = auth_client.post(
        "/api/auth/register",
        json={"username": "bob", "password": "password123"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "AUTH_014"


def test_register_short_password_returns_422(auth_client) -> None:
    r = auth_client.post(
        "/api/auth/register",
        json={"username": "carol", "password": "short"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "AUTH_012"


def test_register_prod_env_returns_403(auth_client, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    try:
        r = auth_client.post(
            "/api/auth/register",
            json={"username": "dave", "password": "password123"},
        )
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "AUTH_010"
    finally:
        monkeypatch.delenv("APP_ENV", raising=False)


# ── login ──────────────────────────────────────────────────────
def _stub_user_row(password_hash: str, *, is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        user_id="alice",
        username="alice",
        password_hash=password_hash,
        tenant_id="acme",
        role="user",
        is_active=is_active,
    )


def test_login_wrong_password_returns_401(auth_client) -> None:
    real_hash = pw_mod.hash_password("correct-password")
    auth_client._session.execute.return_value.fetchone.return_value = _stub_user_row(  # type: ignore[attr-defined]
        real_hash
    )
    r = auth_client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "wrong-password"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "AUTH_001"


def test_login_five_failures_triggers_429(auth_client) -> None:
    real_hash = pw_mod.hash_password("correct-password")
    auth_client._session.execute.return_value.fetchone.return_value = _stub_user_row(  # type: ignore[attr-defined]
        real_hash
    )
    last_status = 200
    for _ in range(5):
        r = auth_client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "wrong-password"},
        )
        last_status = r.status_code
    # 第 5 次失败应触发 429
    assert last_status == 429
    assert r.json()["detail"]["code"] == "AUTH_016"


def test_login_success_returns_new_key(auth_client) -> None:
    real_hash = pw_mod.hash_password("correct-password")
    auth_client._session.execute.return_value.fetchone.return_value = _stub_user_row(  # type: ignore[attr-defined]
        real_hash
    )
    r = auth_client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "correct-password"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_key"].startswith("cg_")
    assert body["role"] == "user"
    assert body["tenant_id"] == "acme"


def test_login_unknown_user_returns_401(auth_client) -> None:
    auth_client._session.execute.return_value.fetchone.return_value = None  # type: ignore[attr-defined]
    r = auth_client.post(
        "/api/auth/login",
        json={"username": "ghost", "password": "whatever"},
    )
    assert r.status_code == 401


# ── audit 联动 ─────────────────────────────────────────────────
def test_register_writes_audit(auth_client, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def _fake_log_audit(background_tasks, **kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(auth_mod, "log_audit", _fake_log_audit)
    auth_client.post(
        "/api/auth/register",
        json={"username": "audit1", "password": "password123"},
    )
    assert any(c.get("action") == "auth.register" for c in calls)


def test_login_writes_audit(auth_client, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def _fake_log_audit(background_tasks, **kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(auth_mod, "log_audit", _fake_log_audit)
    real_hash = pw_mod.hash_password("correct-password")
    auth_client._session.execute.return_value.fetchone.return_value = _stub_user_row(  # type: ignore[attr-defined]
        real_hash
    )
    auth_client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "correct-password"},
    )
    assert any(c.get("action") == "auth.login" for c in calls)
