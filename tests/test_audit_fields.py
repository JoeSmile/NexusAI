"""Wave A A1 — audit optional credential_kind / key_id / run_id / node_id."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from backend.core import audit as audit_mod


def test_write_audit_sync_accepts_new_fields(monkeypatch) -> None:
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
            "tenant_id": "acme",
            "user_id": "alice",
            "action": "test.action",
            "trace_id": "tr-1",
            "input_text": "",
            "output_text": "",
            "model": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
            "latency_ms": 0.0,
            "error_code": None,
            "ip_address": "",
            "user_agent": "",
            "credential_kind": "api_key",
            "key_id": "42",
            "run_id": "run-1",
            "node_id": "node-a",
            "created_at": datetime.utcnow(),
        }
    )

    assert "credential_kind" in captured["sql"]
    assert captured["params"]["credential_kind"] == "api_key"
    assert captured["params"]["key_id"] == "42"
    assert captured["params"]["run_id"] == "run-1"
    assert captured["params"]["node_id"] == "node-a"
    session.commit.assert_called_once()


def test_write_audit_sync_old_call_still_works(monkeypatch) -> None:
    """Callers omitting Wave A fields still insert (defaults to NULL)."""
    captured: dict = {}
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = lambda *a: None

    def _execute(sql, params=None):
        captured["params"] = params
        return MagicMock()

    session.execute.side_effect = _execute
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(audit_mod, "get_pg_session", lambda: factory)

    audit_mod.write_audit_sync(
        {
            "tenant_id": "acme",
            "user_id": "alice",
            "action": "legacy.action",
            "trace_id": "tr-2",
            "input_text": "",
            "output_text": "",
            "model": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
            "latency_ms": 0.0,
            "error_code": None,
            "ip_address": "",
            "user_agent": "",
            "created_at": datetime.utcnow(),
        }
    )

    assert captured["params"]["credential_kind"] is None
    assert captured["params"]["key_id"] is None
    assert captured["params"]["run_id"] is None
    assert captured["params"]["node_id"] is None
