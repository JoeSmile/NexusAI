"""File upload/download must be owner-scoped (no anonymous GET)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routers.files import FILE_ACL_TTL_DEFAULT
from apps.api.routers.files import router as files_router
from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class _Result:
    def __init__(self, row: dict | None) -> None:
        self._row = row

    def first(self) -> dict | None:
        return self._row


class _FakeSession:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def execute(self, _stmt, params: dict | None = None):  # noqa: ANN001
        p = dict(params or {})
        if "path" in p and "key" in p:
            self.rows.append(p)
            return _Result(None)
        key = p.get("key")
        tid = p.get("tid")
        now = datetime.now(UTC)
        for row in self.rows:
            if row.get("key") != key or row.get("tid") != tid:
                continue
            exp = row.get("expires")
            if exp is not None:
                if getattr(exp, "tzinfo", None) is None:
                    exp = exp.replace(tzinfo=UTC)
                if exp <= now:
                    continue
            return _Result({"value": row["path"]})
        return _Result(None)

    def commit(self) -> None:
        return None


class _SessionFactory:
    def __init__(self, inner: _FakeSession) -> None:
        self.inner = inner

    def Session(self):  # noqa: N802
        return self

    def __enter__(self) -> _FakeSession:
        return self.inner

    def __exit__(self, *args: object) -> None:
        return None


@pytest.fixture
def files_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import apps.api.routers.files as files_mod

    store = _FakeSession()
    monkeypatch.setattr(files_mod, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(files_mod, "get_pg_session", lambda: _SessionFactory(store))

    app = FastAPI()
    app.include_router(files_router)

    def _as(tid: str, uid: str, role: str = "user") -> TestClient:
        app.dependency_overrides[verify_human_or_legacy_key] = lambda: TenantContext(
            tid, uid, role, [], False
        )
        return TestClient(app)

    yield _as, store, tmp_path
    app.dependency_overrides.clear()


def test_get_file_requires_auth(files_env) -> None:
    as_client, _, _ = files_env
    client = as_client("t1", "u1")
    app = client.app
    app.dependency_overrides.clear()
    naked = TestClient(app)
    r = naked.get("/api/files/deadbeefdeadbeefdeadbeefdeadbeef.png")
    assert r.status_code in (401, 403)


def test_upload_and_owner_download(files_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FILE_ACL_TTL_SECONDS", raising=False)
    as_client, store, tmp_path = files_env
    owner = as_client("t1", "u1")
    up = owner.post("/api/files/upload", files={"file": ("shot.png", PNG, "image/png")})
    assert up.status_code == 200, up.text
    file_id = up.json()["file_id"]
    assert (tmp_path / "t1" / "u1" / file_id).is_file()

    got = owner.get(f"/api/files/{file_id}")
    assert got.status_code == 200
    assert got.content.startswith(b"\x89PNG")
    assert store.rows[0]["ttl"] == FILE_ACL_TTL_DEFAULT


def test_expired_acl_returns_404_file_still_on_disk(files_env) -> None:
    as_client, store, tmp_path = files_env
    owner = as_client("t1", "u1")
    file_id = owner.post(
        "/api/files/upload", files={"file": ("shot.png", PNG, "image/png")}
    ).json()["file_id"]
    store.rows[0]["expires"] = datetime.now(UTC) - timedelta(seconds=1)
    r = owner.get(f"/api/files/{file_id}")
    assert r.status_code == 404
    assert (tmp_path / "t1" / "u1" / file_id).is_file()


def test_other_user_same_tenant_cannot_download(files_env) -> None:
    as_client, _, _ = files_env
    owner = as_client("t1", "u1")
    file_id = owner.post(
        "/api/files/upload", files={"file": ("shot.png", PNG, "image/png")}
    ).json()["file_id"]
    other = as_client("t1", "u2")
    r = other.get(f"/api/files/{file_id}")
    assert r.status_code == 404


def test_cross_tenant_cannot_download(files_env) -> None:
    as_client, _, _ = files_env
    owner = as_client("t1", "u1")
    file_id = owner.post(
        "/api/files/upload", files={"file": ("shot.png", PNG, "image/png")}
    ).json()["file_id"]
    other = as_client("t2", "u1")
    r = other.get(f"/api/files/{file_id}")
    assert r.status_code == 404
