"""Task 63 — run cancel registry."""

from __future__ import annotations

from packages.plan.run_cancel import (
    RunCancelledError,
    check_cancelled,
    clear_cancel,
    is_cancelled,
    register_run,
    request_cancel,
    unregister_run,
)


def test_cancel_lifecycle() -> None:
    register_run("tr_cancel")
    assert not is_cancelled("tr_cancel")
    assert request_cancel("tr_cancel")
    assert is_cancelled("tr_cancel")
    unregister_run("tr_cancel")
    clear_cancel("tr_cancel")
    assert not is_cancelled("tr_cancel")


def test_request_cancel_unknown_returns_false() -> None:
    assert not request_cancel("tr_missing")


def test_check_cancelled_raises() -> None:
    register_run("tr_raise")
    request_cancel("tr_raise")
    try:
        check_cancelled("tr_raise")
        raised = False
    except RunCancelledError:
        raised = True
    assert raised
    unregister_run("tr_raise")
    clear_cancel("tr_raise")
