"""Task 62 slice 1 — Loop-Guard duplicate detection + session cap."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.core.plan.loop_guard import LoopGuard, LoopGuardError, invoke_fingerprint


def test_fingerprint_stable() -> None:
    a = invoke_fingerprint("cap.a", {"x": 1})
    b = invoke_fingerprint("cap.a", {"x": 1})
    assert a == b
    assert invoke_fingerprint("cap.a", {"x": 2}) != a


def test_duplicate_streak_blocks_on_third(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOP_GUARD_MAX_DUP_STREAK", "3")
    monkeypatch.setenv("LOOP_GUARD_SESSION_CAP", "50")
    guard = LoopGuard()
    payload = {"q": "same"}
    audits: list[dict] = []

    with patch(
        "backend.core.plan.loop_guard.write_audit_sync",
        side_effect=lambda r: audits.append(r) or True,
    ):
        guard.check("cap.a", payload, tenant_id="t1", user_id="u1", trace_id="tr1")
        guard.check("cap.a", payload, tenant_id="t1", user_id="u1", trace_id="tr1")
        with pytest.raises(LoopGuardError, match="重复执行"):
            guard.check("cap.a", payload, tenant_id="t1", user_id="u1", trace_id="tr1")

    assert len(audits) == 1
    assert audits[0]["action"] == "orchestrator.loop_guard"
    assert audits[0]["tenant_id"] == "t1"


def test_session_cap_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOP_GUARD_MAX_DUP_STREAK", "99")
    monkeypatch.setenv("LOOP_GUARD_SESSION_CAP", "2")
    guard = LoopGuard()
    guard.check("cap.a", {"i": 1})
    guard.check("cap.b", {"i": 2})
    with pytest.raises(LoopGuardError, match="上限"):
        guard.check("cap.c", {"i": 3})


def test_different_params_reset_streak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOP_GUARD_MAX_DUP_STREAK", "3")
    guard = LoopGuard()
    guard.check("cap.a", {"n": 1})
    guard.check("cap.a", {"n": 2})
    guard.check("cap.a", {"n": 3})
    # streak reset after different params — no raise
    assert guard._streak_count == 1  # noqa: SLF001
