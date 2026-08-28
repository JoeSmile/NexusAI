"""Task 67 slice 3 — admin console skill_assets management."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from backend.core.errors import NexusAIException, nexusai_exception_handler
from backend.database.pgvector_session import SkillAsset
from apps.api.routers.admin_console import router


def _row(
    *,
    asset_id: str = "ska-1",
    status: str = "draft",
    name: str = "console_skill",
) -> SkillAsset:
    return SkillAsset(
        id=asset_id,
        tenant_id="t1",
        owner_user_id="admin",
        name=name,
        description="admin console test skill",
        cot_template="step one then step two without secrets",
        ir_skeleton={"steps": [{"capability_id": "chat:write", "params": {}}]},
        version=1,
        status=status,
        visibility="private",
        usage_stats={"uses": 3, "successes": 2, "avg_tokens": 120.0},
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@pytest.fixture
def super_admin() -> TenantContext:
    return TenantContext("t1", "sa1", "super_admin", ["admin:*"], True)


@contextmanager
def _client(tenant: TenantContext):
    app = FastAPI()
    app.add_exception_handler(NexusAIException, nexusai_exception_handler)  # type: ignore[arg-type]
    app.include_router(router, prefix="/api")

    async def _auth() -> TenantContext:
        return tenant

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    yield TestClient(app)


def test_skill_list_and_detail(super_admin: TenantContext) -> None:
    row = _row()
    with (
        patch(
            "apps.api.routers.admin_console_skills.list_skill_assets",
            return_value=[row],
        ),
        patch(
            "apps.api.routers.admin_console_skills.evolution_stats",
            return_value={
                "total": 1,
                "by_status": {"draft": 1, "published": 0, "deprecated": 0},
                "mined_draft_queue": 0,
                "total_uses": 3,
                "cache_hit_rate_proxy": 0.6667,
            },
        ),
        patch(
            "apps.api.routers.admin_console_skills._resolve_asset",
            return_value=row,
        ),
        _client(super_admin) as client,
    ):
        r = client.get("/api/admin/console/skills")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["usage"]["uses"] == 3

        r = client.get("/api/admin/console/skills/ska-1")
        assert r.status_code == 200
        assert r.json()["cot_template"]


def test_skill_publish_and_deprecate(super_admin: TenantContext) -> None:
    draft = _row(status="draft")
    published = _row(status="published", name="console_skill")
    published.version = 2
    deprecated = _row(status="deprecated", name="console_skill")
    with (
        patch(
            "apps.api.routers.admin_console_skills._resolve_asset",
            side_effect=[draft, draft, published, published],
        ),
        patch(
            "apps.api.routers.admin_console_skills.publish",
            return_value=published,
        ) as pub,
        patch(
            "apps.api.routers.admin_console_skills.deprecate",
            return_value=deprecated,
        ) as dep,
        _client(super_admin) as client,
    ):
        r = client.post("/api/admin/console/skills/ska-1/publish")
        assert r.status_code == 200
        assert r.json()["item"]["status"] == "published"
        pub.assert_called_once()

        r = client.post("/api/admin/console/skills/ska-1/deprecate")
        assert r.status_code == 200
        assert r.json()["item"]["status"] == "deprecated"
        dep.assert_called_once()


def test_skill_reject_draft(super_admin: TenantContext) -> None:
    draft = _row(status="draft")
    with (
        patch(
            "apps.api.routers.admin_console_skills._resolve_asset",
            return_value=draft,
        ),
        patch(
            "apps.api.routers.admin_console_skills.reject_draft",
            return_value=True,
        ) as rej,
        _client(super_admin) as client,
    ):
        r = client.post("/api/admin/console/skills/ska-1/reject")
        assert r.status_code == 200
        rej.assert_called_once_with(tenant_id="t1", asset_id="ska-1")


def test_skill_publish_gate_error(super_admin: TenantContext) -> None:
    draft = _row(status="draft")
    with (
        patch(
            "apps.api.routers.admin_console_skills._resolve_asset",
            return_value=draft,
        ),
        patch(
            "apps.api.routers.admin_console_skills.publish",
            side_effect=HTTPException(
                status_code=400,
                detail={"code": "GATE_SECRET", "message": "secret_detected"},
            ),
        ),
        _client(super_admin) as client,
    ):
        r = client.post("/api/admin/console/skills/ska-1/publish")
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "GATE_SECRET"
