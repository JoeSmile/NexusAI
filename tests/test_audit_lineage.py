"""Task 56 切片 5 — 审计血缘 + NDJSON 回放。"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import packages.audit as audit_mod
from backend.core.audit_context import bind_audit_lineage, clear_audit_lineage, get_audit_lineage
from packages.capability.governance_chain import DecisionExplain


def test_lineage_context_bind() -> None:
    clear_audit_lineage()
    bind_audit_lineage(trace_id="tr-1", parent_trace_id=None, tool_use_id="tu-1")
    lin = get_audit_lineage()
    assert lin.trace_id == "tr-1"
    assert lin.tool_use_id == "tu-1"
    clear_audit_lineage()


def test_write_audit_includes_lineage_fields(monkeypatch) -> None:
    captured: dict = {}
    session = __import__("unittest.mock").mock.MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None

    def _execute(sql, params=None):
        captured["sql"] = str(sql)
        captured["params"] = params
        return __import__("unittest.mock").mock.MagicMock()

    session.execute.side_effect = _execute
    factory = __import__("unittest.mock").mock.MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(audit_mod, "get_pg_session", lambda: factory)

    audit_mod.write_audit_sync(
        {
            "tenant_id": "t1",
            "user_id": "u1",
            "action": "capability.governance",
            "trace_id": "tr-1",
            "parent_trace_id": "tr-parent",
            "tool_use_id": "tu-1",
            "decision_explain": '{"allowed":true}',
            "input_text": "cap.a",
            "output_text": "{}",
            "model": "cap.a",
            "created_at": datetime.utcnow(),
        }
    )
    assert "parent_trace_id" in captured["sql"]
    assert captured["params"]["tool_use_id"] == "tu-1"
    assert captured["params"]["decision_explain"] == '{"allowed":true}'


def test_write_governance_audit(monkeypatch) -> None:
    captured: list[dict] = []
    monkeypatch.setattr(
        audit_mod,
        "write_audit_sync",
        lambda rec: captured.append(rec) or True,
    )
    explain = DecisionExplain(allowed=True, reason="allow")
    explain.stages.append({"stage": "policy", "decision": "allow"})
    ok = audit_mod.write_governance_audit(
        tenant_id="t1",
        user_id="u1",
        capability_id="hotspot.dig",
        explain=explain.to_dict(),
        lineage=get_audit_lineage(),
        langfuse_ids={"langfuse_trace_id": "lf-1"},
    )
    assert ok is True
    assert captured[0]["action"] == "capability.governance"
    payload = json.loads(captured[0]["decision_explain"])
    assert payload["langfuse"]["langfuse_trace_id"] == "lf-1"


def test_ndjson_mapping_turn_and_tool() -> None:
    chat = SimpleNamespace(
        id=1,
        tenant_id="t1",
        user_id="u1",
        action="chat",
        trace_id="tr-1",
        parent_trace_id=None,
        tool_use_id=None,
        decision_explain=None,
        input_text="hello",
        output_text="hi",
        model="m",
        error_code=None,
        latency_ms=1.0,
        cost=0.0,
        created_at=datetime(2026, 8, 22, 10, 0, 0),
    )
    gov = SimpleNamespace(
        id=2,
        tenant_id="t1",
        user_id="u1",
        action="capability.governance",
        trace_id="tr-1",
        parent_trace_id="tr-1",
        tool_use_id="tu-1",
        decision_explain='{"allowed":true,"stages":[]}',
        input_text="cap.a",
        output_text="{}",
        model="cap.a",
        error_code=None,
        latency_ms=0.0,
        cost=0.0,
        created_at=datetime(2026, 8, 22, 10, 0, 1),
    )
    invoke = SimpleNamespace(
        id=3,
        tenant_id="t1",
        user_id="u1",
        action="capability.invoke",
        trace_id="tr-1",
        parent_trace_id="tr-1",
        tool_use_id="tu-1",
        decision_explain=None,
        input_text="cap.a",
        output_text="result",
        model="cap.a",
        error_code=None,
        latency_ms=12.0,
        cost=0.01,
        created_at=datetime(2026, 8, 22, 10, 0, 2),
    )
    lines = list(audit_mod.ndjson_lines_from_rows([invoke, gov, chat]))
    assert len(lines) == 3
    events = [json.loads(line) for line in lines]
    assert events[0]["type"] == "turn_begin"
    assert events[1]["type"] == "tool_call"
    assert events[1]["decision_explain"]["allowed"] is True
    assert events[2]["type"] == "tool_result"
    assert events[2]["ok"] is True


def test_ndjson_memory_event_includes_preview() -> None:
  mem = SimpleNamespace(
      id=4,
      tenant_id="t1",
      user_id="u1",
      action="memory.rag_sanitize",
      trace_id="tr-mem",
      parent_trace_id=None,
      tool_use_id=None,
      decision_explain=None,
      input_text="hello",
      output_text='{"rag_retrieved_ids":["doc-1"],"flags":{"injection":1},"redacted_fragments":2}',
      model="memory",
      error_code=None,
      latency_ms=None,
      cost=None,
      created_at=datetime(2026, 8, 22, 11, 0, 0),
  )
  events = audit_mod.audit_row_to_ndjson_events(mem)
  assert len(events) == 1
  assert events[0]["type"] == "memory_event"
  assert events[0]["action"] == "memory.rag_sanitize"
  assert "doc-1" in events[0]["output_preview"]
