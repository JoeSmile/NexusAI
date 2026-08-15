"""E3.4 — scheduler cron helpers + I3/I6 fail-closed."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.core.workflow.scheduler import (
    _user_still_valid,
    parse_cron_next,
    scan_due_schedules,
)


def test_cron_rejects_seconds_or_dow():
    with pytest.raises(ValueError):
        parse_cron_next("0 8 * * 1")
    with pytest.raises(ValueError):
        parse_cron_next("0 8 1 * *")


def test_cron_same_day_if_before():
    after = datetime(2026, 8, 15, 7, 0, 0)
    nxt = parse_cron_next("0 8 * * *", after=after)
    assert nxt == datetime(2026, 8, 15, 8, 0, 0)


def test_user_still_valid_requires_active_key():
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = (1,)
    assert _user_still_valid(session, tenant_id="t", user_id="u1") is True
    session.query.return_value.filter.return_value.first.return_value = None
    assert _user_still_valid(session, tenant_id="t", user_id="u1") is False


def test_scan_auth_check_fail_does_not_start_run():
    """I3：validate 抛异常 → 不 start_run，推进 next_run_at。"""
    sched = MagicMock()
    sched.id = "sid-1"
    sched.enabled = True
    sched.tenant_id = "t1"
    sched.workflow_id = "wf1"
    sched.created_by = "u1"
    sched.cron = "0 8 * * *"
    sched.run_inputs = {}
    sched.org_unit_id = "ou1"
    sched.next_run_at = datetime(2026, 8, 15, 7, 0, 0)

    session = MagicMock()
    session.execute.return_value.scalar.side_effect = [True, True]  # lock + unlock
    session.execute.return_value.fetchall.return_value = [("sid-1",)]
    session.query.return_value.filter.return_value.one_or_none.return_value = sched
    session.query.return_value.filter.return_value.count.return_value = 0

    sf = MagicMock()
    sf.Session.return_value.__enter__.return_value = session
    sf.Session.return_value.__exit__.return_value = False

    with patch(
        "backend.database.pgvector_session.get_pg_session", return_value=sf
    ), patch(
        "backend.core.workflow.scheduler._user_still_valid", return_value=True
    ), patch(
        "backend.core.workflow.scheduler.validate_grants_before_execute",
        side_effect=RuntimeError("boom"),
    ), patch(
        "backend.core.workflow.scheduler._audit_schedule"
    ) as audit, patch(
        "backend.core.workflow.runner.start_run"
    ) as start_run, patch(
        "backend.core.workflow.runner.schedule_execute"
    ):
        out = scan_due_schedules(now=datetime(2026, 8, 15, 8, 0, 0), limit=5)

    assert out["triggered"] == 0
    assert out["skipped"] >= 1
    start_run.assert_not_called()
    assert any(
        c.kwargs.get("action") == "workflow.run.auth_check_failed"
        for c in audit.call_args_list
    )
