"""Task 43.3 — miner from chat.task_plan audit."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from packages.skill_assets import miner
from backend.database.pgvector_session import SkillAsset, get_pg_session


@pytest.fixture()
def ensure_table():
    sf = get_pg_session()
    SkillAsset.__table__.create(sf.engine, checkfirst=True)
    yield sf


@pytest.mark.asyncio
async def test_mine_candidates_creates_draft(ensure_table, monkeypatch):
    tid = f"mine-{uuid.uuid4().hex[:8]}"
    sf = ensure_table

    monkeypatch.setattr(
        miner,
        "fetch_task_plan_audits",
        lambda **kw: [
            {
                "plan": {
                    "steps": [{"capability_id": "c1", "params": {}}],
                },
                "session_id": "s1",
                "trace_id": "tr1",
            }
        ],
    )
    monkeypatch.setattr(miner, "search_published", lambda **kw: [])

    async def fake_gen(*a, **k):
        return SimpleNamespace(
            success=True,
            output=json.dumps(
                {
                    "name": "mined_plan",
                    "cot_template": "do A then B",
                    "ir_skeleton": {"steps": [{"capability_id": "c1", "params": {}}]},
                }
            ),
            error=None,
            metadata={},
            latency_ms=1.0,
        )

    monkeypatch.setattr(miner.harness, "generate", fake_gen)

    ids = await miner.mine_candidates(
        tenant_id=tid, owner_user_id="admin", name_hint="mined_plan"
    )
    assert len(ids) == 1
    with sf.Session() as session:
        row = session.query(SkillAsset).filter(SkillAsset.id == ids[0]).one()
        assert row.status == "draft"
        session.delete(row)
        session.commit()


@pytest.mark.asyncio
async def test_mine_failure_silent(monkeypatch):
    monkeypatch.setattr(miner, "fetch_task_plan_audits", lambda **kw: (_ for _ in ()).throw(RuntimeError("x")))
    out = await miner.mine_candidates(tenant_id="t", owner_user_id="u")
    assert out == []
