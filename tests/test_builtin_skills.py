"""Task 66 slice 2 — builtin skills + skill_assets catalog."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.core.skill_assets.bootstrap import (
    bootstrap_builtin_skill_assets,
    validate_builtin_catalog,
)
from backend.core.skill_assets.builtin_catalog import BUILTIN_SKILL_ASSET_CATALOG, BUILTIN_SKILL_IDS
from backend.skills.registry import SkillRegistry


def test_discover_builtin_skills() -> None:
    reg = SkillRegistry()
    reg.discover()
    for sid in BUILTIN_SKILL_IDS:
        assert reg.get_skill(sid) is not None, sid
    assert reg.get_skill("greeting") is not None


@pytest.mark.asyncio
async def test_refund_policy_executes() -> None:
    reg = SkillRegistry()
    reg.discover()
    skill = reg.get_skill("refund_policy")
    assert skill is not None
    result = await skill.execute(
        entities={"order_id": "ORD-1", "reason": "duplicate charge"},
        tenant_id="t1",
        user_context={"user_id": "u1", "permissions": ["chat:write"]},
    )
    assert result.success is True
    assert "ORD-1" in result.output


@pytest.mark.asyncio
async def test_complaint_escalation_requires_approval() -> None:
    reg = SkillRegistry()
    reg.discover()
    skill = reg.get_skill("complaint_escalation")
    assert skill is not None
    with patch.object(
        skill,
        "_create_approval_request",
        new=AsyncMock(return_value="apr_test_1"),
    ):
        result = await skill.execute(
            entities={"topic": "delivery delay"},
            tenant_id="t1",
            user_context={"user_id": "u1", "permissions": ["chat:write"]},
        )
    assert result.success is False
    assert result.error == "PENDING_APPROVAL"
    assert result.approval_request_id == "apr_test_1"


def test_catalog_passes_publish_gates() -> None:
    ids = validate_builtin_catalog()
    assert len(ids) == len(BUILTIN_SKILL_ASSET_CATALOG) == 7


def test_weekly_report_demo_chain_parallel_steps() -> None:
    entry = next(e for e in BUILTIN_SKILL_ASSET_CATALOG if e["skill_id"] == "weekly_report")
    steps = entry["ir_skeleton"]["steps"]
    by_id = {s["id"]: s for s in steps}
    assert by_id["dig"]["depends_on"] == []
    assert by_id["metrics"]["depends_on"] == []
    assert set(by_id["report"]["depends_on"]) == {"dig", "metrics"}


def test_bootstrap_skill_assets_idempotent(ensure_skill_table):
    import uuid

    from backend.database.pgvector_session import SkillAsset

    tid = f"bsk-{uuid.uuid4().hex[:8]}"
    sf = ensure_skill_table
    first = bootstrap_builtin_skill_assets(tenant_id=tid, owner_user_id="admin")
    second = bootstrap_builtin_skill_assets(tenant_id=tid, owner_user_id="admin")
    assert len(first) == 7
    assert first == second
    with sf.Session() as session:
        count = (
            session.query(SkillAsset)
            .filter(SkillAsset.tenant_id == tid, SkillAsset.status == "published")
            .count()
        )
        assert count == 7
        session.query(SkillAsset).filter(SkillAsset.tenant_id == tid).delete()
        session.commit()


@pytest.fixture()
def ensure_skill_table():
    from sqlalchemy import text

    from backend.database.pgvector_session import SkillAsset, get_pg_session

    sf = get_pg_session()
    try:
        with sf.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("postgres unavailable")
    SkillAsset.__table__.create(sf.engine, checkfirst=True)
    yield sf
