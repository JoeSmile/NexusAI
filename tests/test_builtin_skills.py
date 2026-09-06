"""Task 66 slice 2 — builtin skills + skill_assets catalog."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from packages.skill_assets.bootstrap import (
    bootstrap_builtin_skill_assets,
    validate_builtin_catalog,
)
from packages.skill_assets.builtin_catalog import (
    BUILTIN_SKILL_ASSET_CATALOG,
    BUILTIN_SKILL_IDS,
)
from packages.skills.registry import SKILL_REGISTRY, SkillRegistry
from packages.workflow.ir import WorkflowIR


def test_discover_builtin_skills() -> None:
    reg = SkillRegistry()
    reg.load()
    for sid in BUILTIN_SKILL_IDS:
        assert reg.get_skill(sid) is not None, sid
    assert reg.get_skill("greeting") is not None


def test_catalog_ids_are_registry_subset_with_cot() -> None:
    assert BUILTIN_SKILL_IDS <= set(SKILL_REGISTRY)
    assert "greeting" not in BUILTIN_SKILL_IDS
    for sid in SKILL_REGISTRY:
        skill = SKILL_REGISTRY[sid]
        if getattr(skill, "cot_template", ""):
            assert sid in BUILTIN_SKILL_IDS


@pytest.mark.asyncio
async def test_refund_policy_executes() -> None:
    reg = SkillRegistry()
    reg.load()
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
    reg.load()
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
    assert len(ids) == len(BUILTIN_SKILL_ASSET_CATALOG) == len(BUILTIN_SKILL_IDS)


def test_weekly_report_workflow_ir_chain() -> None:
    skill = SKILL_REGISTRY["weekly_report"]
    ir = WorkflowIR.model_validate(skill.workflow_ir)
    caps = {n.capability_id for n in ir.nodes}
    assert "analytics.summary" in caps
    assert "llm.generate" in caps
    assert ir.edges
    edge = ir.edges[0]
    assert edge.from_node_id == "summary"
    assert edge.from_field == "result"
    assert edge.to_node_id == "generate"
    assert edge.to_param == "instruction"
    # catalog snapshot must match engine IR, not legacy steps[]
    entry = next(e for e in BUILTIN_SKILL_ASSET_CATALOG if e["skill_id"] == "weekly_report")
    assert entry["ir_skeleton"] == skill.workflow_ir


def test_bootstrap_skill_assets_idempotent(ensure_skill_table):
    import uuid

    from packages.database.pgvector_session import SkillAsset

    tid = f"bsk-{uuid.uuid4().hex[:8]}"
    sf = ensure_skill_table
    first = bootstrap_builtin_skill_assets(tenant_id=tid, owner_user_id="admin")
    second = bootstrap_builtin_skill_assets(tenant_id=tid, owner_user_id="admin")
    assert len(first) == len(BUILTIN_SKILL_IDS)
    assert first == second
    with sf.Session() as session:
        count = (
            session.query(SkillAsset)
            .filter(SkillAsset.tenant_id == tid, SkillAsset.status == "published")
            .count()
        )
        assert count == len(BUILTIN_SKILL_IDS)
        session.query(SkillAsset).filter(SkillAsset.tenant_id == tid).delete()
        session.commit()


@pytest.fixture()
def ensure_skill_table():
    from sqlalchemy import text

    from packages.database.pgvector_session import SkillAsset, get_pg_session

    sf = get_pg_session()
    try:
        with sf.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("postgres unavailable")
    SkillAsset.__table__.create(sf.engine, checkfirst=True)
    yield sf
