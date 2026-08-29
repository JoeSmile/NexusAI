"""Semi-auto miner: chat.task_plan audit → draft skill_assets (Task 43.3)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import text

from packages.database.pgvector_session import get_pg_session
from packages.harness import LLMHarness
from packages.skill_assets.service import create_draft, search_published

logger = logging.getLogger(__name__)
harness = LLMHarness()
_JSON_RE = re.compile(r"\{[\s\S]*\}")


def fetch_task_plan_audits(
    *,
    tenant_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """扫 audit_logs action=chat.task_plan。"""
    sf = get_pg_session()
    with sf.Session() as session:
        rows = session.execute(
            text(
                """
                SELECT id, tenant_id, user_id, trace_id, output_text, created_at
                FROM audit_logs
                WHERE tenant_id = :tid AND action = 'chat.task_plan'
                ORDER BY created_at DESC
                LIMIT :lim
                """
            ),
            {"tid": tenant_id, "lim": limit},
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            plan = None
            session_id = None
            try:
                blob = json.loads(r.output_text or "{}")
                if isinstance(blob, dict):
                    plan = blob.get("plan") or blob
                    session_id = blob.get("session_id")
            except json.JSONDecodeError:
                continue
            out.append(
                {
                    "audit_id": r.id,
                    "tenant_id": r.tenant_id,
                    "user_id": r.user_id,
                    "trace_id": r.trace_id,
                    "session_id": session_id,
                    "plan": plan,
                }
            )
        return out


async def mine_candidates(
    *,
    tenant_id: str,
    owner_user_id: str,
    limit: int = 20,
    name_hint: str | None = None,
) -> list[str]:
    """
    从 N 条轨迹归纳一个 draft（失败静默 → []）。
    返回新建 draft id 列表。
    """
    try:
        traces = fetch_task_plan_audits(tenant_id=tenant_id, limit=limit)
        if len(traces) < 1:
            return []

        name = (name_hint or f"mined_{tenant_id[:8]}").strip()[:120]
        # 去重：已有同名 published / 高相似则 ADD-only 跳过
        hits = search_published(tenant_id=tenant_id, query=name, limit=1, min_score=0.92)
        if hits:
            return []

        plans = [t.get("plan") for t in traces if t.get("plan")]
        prompt = (
            "Summarize these task plans into one CoT template and IR skeleton JSON:\n"
            '{"name":"...","cot_template":"...","ir_skeleton":{"steps":[...]}}\n'
            f"plans={json.dumps(plans[:10], ensure_ascii=False)[:3000]}"
        )
        result = await harness.generate(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            tenant_id=tenant_id,
            max_tokens=600,
        )
        if not result.success:
            return []
        raw = str(result.output or "")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            m = _JSON_RE.search(raw)
            if not m:
                return []
            data = json.loads(m.group(0))
        if not isinstance(data, dict):
            return []
        cot = str(data.get("cot_template") or "")[:4000]
        skeleton = data.get("ir_skeleton") if isinstance(data.get("ir_skeleton"), dict) else {}
        asset_name = str(data.get("name") or name)[:128]
        row = create_draft(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            name=asset_name,
            description="mined_from_chat.task_plan",
            cot_template=cot,
            ir_skeleton=skeleton,
            visibility="private",
            embed=True,
        )
        return [row.id]
    except Exception:
        logger.debug("skill_assets mine failed", exc_info=True)
        return []
