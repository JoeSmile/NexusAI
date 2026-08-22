"""Task 56 offline smoke — no API server / LLM key required.

  uv run python scripts/smoke_task56_offline.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.audit import audit_row_to_ndjson_events, write_governance_audit
from backend.core.plan.event_bus import get_run_bus, release_run_bus
from backend.core.plan.models import PlanIR, PlanStep
from backend.pipeline.nodes.orchestrator import execute_plan_ir
from backend.pipeline.state import make_initial_state


async def _main() -> None:
  trace = "smoke_task56"
  release_run_bus(trace)
  bus = get_run_bus(trace)
  bus.publish_plan(
      goal="smoke",
      steps=[{"id": "s1", "capability_id": "cap.a", "depends_on": []}],
  )
  bus.publish_step("s1", capability_id="cap.a", status="succeeded", summary="ok")
  snap = bus.snapshot_dict()
  assert snap["goal"] == "smoke"
  assert len(snap["events"]) >= 2

  state = make_initial_state("t1", "u1", "s1", "hello")
  state["user_context"] = {
      "tenant_id": "t1",
      "user_id": "u1",
      "role": "user",
      "permissions": ["chat:write"],
      "is_cross_tenant": False,
  }
  plan = PlanIR(
      goal="p",
      steps=[PlanStep(id="s1", capability_id="cap.a", params={})],
      version=1,
  )

  async def fake_collect(cap_id, payload, tenant):
      return {
          "ok": True,
          "output": f"out:{cap_id}",
          "text": f"out:{cap_id}",
          "capability_id": cap_id,
      }

  import backend.pipeline.nodes.orchestrator as orch

  orch._collect_invoke = fake_collect  # type: ignore[method-assign]
  orch._list_visible_capabilities = lambda s: [{"id": "cap.a", "param_spec": {}}]  # type: ignore

  results, _, _, _ = await execute_plan_ir(state, plan)
  assert results["s1"]["output"] == "out:cap.a"

  ok = write_governance_audit(
      tenant_id="t1",
      user_id="u1",
      capability_id="cap.a",
      explain={"allowed": True, "stages": [], "reason": "allow"},
  )
  assert ok is True

  row = SimpleNamespace(
      id=1,
      tenant_id="t1",
      user_id="u1",
      action="capability.governance",
      trace_id=trace,
      parent_trace_id=trace,
      tool_use_id="tu-1",
      decision_explain='{"allowed":true}',
      input_text="cap.a",
      output_text="{}",
      model="cap.a",
      error_code=None,
      latency_ms=0.0,
      cost=0.0,
      created_at=__import__("datetime").datetime.utcnow(),
  )
  events = audit_row_to_ndjson_events(row)
  assert events[0]["type"] == "tool_call"

  print("smoke_task56_offline: OK")
  print(json.dumps({"snapshot_events": len(snap["events"]), "step_output": results["s1"]["output"]}))


if __name__ == "__main__":
  asyncio.run(_main())
