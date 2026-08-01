"""A/B 管理路由（Task 23.03）— TestClient + 桩 auth/DB"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.auth.api_key_auth import verify_api_key
from backend.core.auth.models import TenantContext
from backend.routers import ab as ab_mod
from backend.routers.ab import router


@pytest.fixture
def admin_client(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def _admin() -> TenantContext:
        return TenantContext("acme", "admin", "super_admin", [], True)

    app.dependency_overrides[verify_api_key] = _admin

    # 默认空会话桩，具体用例可再改 monkeypatch
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None
    session.execute.return_value.fetchone.return_value = None
    session.execute.return_value.fetchall.return_value = []
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(ab_mod, "get_pg_session", lambda: factory)

    client = TestClient(app)
    client._session = session  # type: ignore[attr-defined]
    yield client
    app.dependency_overrides.clear()


def test_create_experiment_groups_weights_mismatch(admin_client):
    r = admin_client.post(
        "/api/ab/experiments",
        json={
            "experiment_id": "e1",
            "name": "bad",
            "groups": ["A", "B"],
            "weights": [1.0],
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "AB_001"


def test_create_experiment_ok(admin_client):
    r = admin_client.post(
        "/api/ab/experiments",
        json={
            "experiment_id": "e1",
            "name": "prompt test",
            "groups": ["A", "B"],
            "weights": [0.5, 0.5],
            "variant_configs": {"B": {"system_prompt": "be brief"}},
        },
    )
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "experiment_id": "e1"}
    admin_client._session.commit.assert_called()  # type: ignore[attr-defined]


def test_list_experiments_shape(admin_client, monkeypatch):
    row = SimpleNamespace(
        experiment_id="e1",
        name="n",
        description="d",
        groups='["A","B"]',
        weights="[0.5,0.5]",
        enabled=True,
        extra_metadata='{"variant_configs":{"A":{}}}',
        created_at=datetime(2026, 8, 1),
        updated_at=datetime(2026, 8, 1),
    )
    session = admin_client._session  # type: ignore[attr-defined]
    session.execute.return_value.fetchall.return_value = [row]

    r = admin_client.get("/api/ab/experiments")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["experiment_id"] == "e1"
    assert data[0]["groups"] == ["A", "B"]
    assert data[0]["variant_configs"] == {"A": {}}


def test_stats_shape(admin_client):
    session = admin_client._session  # type: ignore[attr-defined]

    def _execute(sql: Any, params: dict | None = None):
        s = str(sql)
        m = MagicMock()
        if "ab_test_events" in s:
            m.fetchall.return_value = [
                SimpleNamespace(group="A", event_type="exposure", cnt=3)
            ]
        else:
            m.fetchall.return_value = [SimpleNamespace(group="A", cnt=2)]
        return m

    session.execute.side_effect = _execute
    r = admin_client.get("/api/ab/stats/e1")
    assert r.status_code == 200
    body = r.json()
    assert body["experiment_id"] == "e1"
    assert body["assignments"] == {"A": 2}
    assert body["events"][0]["event_type"] == "exposure"
