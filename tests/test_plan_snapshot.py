"""plan_snapshot API tests."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.auth.models import TenantContext
from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.plan.event_bus import get_run_bus, release_run_bus
from backend.core.plan.run_cancel import clear_cancel, register_run, unregister_run
from backend.routers.plan_snapshot import router


def _tenant() -> TenantContext:
    return TenantContext(
        tenant_id="t1",
        user_id="u1",
        role="user",
        extra_permissions=["chat:read", "chat:write"],
        is_cross_tenant=False,
    )


def test_snapshot_endpoint_returns_events():
    release_run_bus("tr_api")
    bus = get_run_bus("tr_api")
    bus.publish_plan(goal="g", steps=[{"id": "s1", "capability_id": "cap.a"}])

    app = FastAPI()
    app.include_router(router)

    async def _auth() -> TenantContext:
        return _tenant()

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    client = TestClient(app)
    res = client.get("/api/chat/run/tr_api/snapshot")
    assert res.status_code == 200
    body = res.json()
    assert body["trace_id"] == "tr_api"
    assert body["snapshot"]["goal"] == "g"
    assert len(body["events"]) >= 1
    app.dependency_overrides.clear()
    release_run_bus("tr_api")


def test_cancel_active_run():
    release_run_bus("tr_cancel")
    register_run("tr_cancel")
    bus = get_run_bus("tr_cancel")

    app = FastAPI()
    app.include_router(router)

    async def _auth() -> TenantContext:
        return _tenant()

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    client = TestClient(app)
    res = client.delete("/api/chat/streaming/tr_cancel")
    assert res.status_code == 200
    body = res.json()
    assert body["cancelled"] is True
    events = [e.type for e in bus.events_all()]
    assert "cancelled" in events
    app.dependency_overrides.clear()
    unregister_run("tr_cancel")
    clear_cancel("tr_cancel")
    release_run_bus("tr_cancel")


def test_snapshot_not_found():
    app = FastAPI()
    app.include_router(router)

    async def _auth() -> TenantContext:
        return _tenant()

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    client = TestClient(app)
    res = client.get("/api/chat/run/missing_trace/snapshot")
    assert res.status_code == 404
    app.dependency_overrides.clear()
