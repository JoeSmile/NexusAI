"""Audit write failure metric + alert hook (Task 59 S3) + breaker (Task 81)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import packages.audit as audit_mod


@pytest.fixture(autouse=True)
def _reset_audit_breaker() -> None:
    audit_mod.reset_audit_breaker_for_tests()


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


def test_audit_breaker_skips_db_after_consecutive_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit_mod, "AUDIT_BREAKER_FAILS", 2)
    monkeypatch.setattr(audit_mod, "AUDIT_BREAKER_TTL_S", 60.0)
    session_factory = MagicMock()
    session_factory.Session.side_effect = RuntimeError("db down")
    get_pg = MagicMock(return_value=session_factory)
    monkeypatch.setattr(audit_mod, "get_pg_session", get_pg)
    with patch.object(audit_mod, "_alert_audit_write_failure"):
        assert audit_mod.write_audit_sync({"tenant_id": "t1", "user_id": "u1", "action": "a"}) is False
        assert audit_mod.write_audit_sync({"tenant_id": "t1", "user_id": "u1", "action": "b"}) is False
        calls_before = get_pg.call_count
        assert audit_mod.audit_circuit_open() is True
        assert audit_mod.write_audit_sync({"tenant_id": "t1", "user_id": "u1", "action": "c"}) is False
        assert get_pg.call_count == calls_before


def test_audit_breaker_logs_traceback_once_per_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit_mod, "AUDIT_BREAKER_FAILS", 1)
    monkeypatch.setattr(audit_mod, "AUDIT_BREAKER_TTL_S", 60.0)
    session_factory = MagicMock()
    session_factory.Session.side_effect = RuntimeError("db down")
    monkeypatch.setattr(audit_mod, "get_pg_session", lambda: session_factory)
    with (
        patch.object(audit_mod.logger, "exception") as exc_log,
        patch.object(audit_mod.logger, "warning") as warn_log,
        patch.object(audit_mod, "_alert_audit_write_failure") as alert,
    ):
        audit_mod.write_audit_sync({"tenant_id": "t1", "user_id": "u1", "action": "a"})
        audit_mod.write_audit_sync({"tenant_id": "t1", "user_id": "u1", "action": "b"})
    assert exc_log.call_count == 1
    assert alert.call_count == 1
    assert warn_log.call_count >= 1


def test_audit_breaker_closes_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_mod, "AUDIT_BREAKER_FAILS", 1)
    monkeypatch.setattr(audit_mod, "AUDIT_BREAKER_TTL_S", 10.0)
    down = MagicMock()
    down.Session.side_effect = RuntimeError("db down")
    monkeypatch.setattr(audit_mod, "get_pg_session", lambda: down)
    with patch.object(audit_mod, "_alert_audit_write_failure"):
        assert audit_mod.write_audit_sync({"tenant_id": "t1", "user_id": "u1", "action": "a"}) is False
        assert audit_mod.audit_circuit_open() is True
    audit_mod._breaker_open_until = 0.0
    inner = MagicMock()
    inner.execute.return_value.fetchone.return_value = None
    ok_cm = MagicMock()
    ok_cm.__enter__.return_value = inner
    ok_session = MagicMock()
    ok_session.Session.return_value = ok_cm
    monkeypatch.setattr(audit_mod, "get_pg_session", lambda: ok_session)
    with patch.object(audit_mod, "_alert_audit_write_failure"):
        assert audit_mod.write_audit_sync({"tenant_id": "t1", "user_id": "u1", "action": "b"}) is True
        assert audit_mod.audit_circuit_open() is False
