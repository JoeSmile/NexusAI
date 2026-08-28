"""Task 65 slice 0 — intent telemetry on audit_logs."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.core import audit as audit_mod
from packages.pipeline.nodes.analyze_parallel import analyze_parallel
from packages.pipeline.state import make_initial_state


def test_write_audit_sync_accepts_intent_fields(monkeypatch) -> None:
    captured: dict = {}
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None

    def _execute(sql, params=None):
        captured["sql"] = str(sql)
        captured["params"] = params
        return MagicMock()

    session.execute.side_effect = _execute
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(audit_mod, "get_pg_session", lambda: factory)

    audit_mod.write_audit_sync(
        {
            "tenant_id": "t1",
            "user_id": "u1",
            "action": "chat",
            "trace_id": "tr_1",
            "intent_predicted": "greeting",
            "intent_confidence": 0.91,
            "intent_source": "rule",
        }
    )

    assert "intent_predicted" in captured["sql"]
    assert captured["params"]["intent_predicted"] == "greeting"
    assert captured["params"]["intent_confidence"] == 0.91
    assert captured["params"]["intent_source"] == "rule"
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_parallel_sets_intent_source(monkeypatch) -> None:
    def fake_detect(self, text: str):
        result = MagicMock()
        result.intent = MagicMock(value="knowledge_query")
        result.confidence = 0.88
        result.source = "rule"
        return result

    monkeypatch.setattr(
        "packages.intent.core.intent_classifier.IntentClassifier.detect_intent",
        fake_detect,
    )
    state = make_initial_state("t1", "u1", "s1", "制度在哪")
    out = await analyze_parallel(state)
    assert out["intent"] == "knowledge_query"
    assert out["intent_confidence"] == 0.88
    assert out["intent_source"] == "rule"
