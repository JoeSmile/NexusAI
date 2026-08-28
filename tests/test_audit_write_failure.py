"""Audit write failure metric + alert hook (Task 59 S3)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import packages.audit as audit_mod


@pytest.fixture(autouse=True)
def _reset_audit_failure_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_mod, "_audit_write_failure_count", 0, raising=False)


def test_write_audit_failure_increments_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory = MagicMock()
    session_factory.Session.side_effect = RuntimeError("db down")
    monkeypatch.setattr(audit_mod, "get_pg_session", lambda: session_factory)
    with patch.object(audit_mod, "_alert_audit_write_failure"):
        ok = audit_mod.write_audit_sync({"tenant_id": "t1", "user_id": "u1", "action": "chat"})
    assert ok is False
    assert audit_mod.audit_write_failure_count() == 1


def test_write_audit_failure_triggers_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    session_factory = MagicMock()
    session_factory.Session.side_effect = RuntimeError("db down")
    monkeypatch.setattr(audit_mod, "get_pg_session", lambda: session_factory)
    notify = MagicMock(return_value=True)
    monkeypatch.setattr("packages.notification.notify", notify)
    audit_mod.write_audit_sync(
        {
            "tenant_id": "t1",
            "user_id": "u1",
            "action": "chat",
            "trace_id": "trace-1",
        }
    )
    notify.assert_called_once()
    args = notify.call_args[0]
    assert args[0] == "t1"
    assert args[1] == "u1"
    assert args[2] == "security.audit_write_failed"
