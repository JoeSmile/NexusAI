"""Run status machine (Wave D1)."""

from __future__ import annotations

from typing import Literal

RunStatus = Literal["pending", "running", "succeeded", "failed"]
NodeStatus = Literal["pending", "running", "succeeded", "failed"]

_ALLOWED: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "failed"}),  # failed: 并发超限/预检失败直接终态(execute_run 429 路径)
    "running": frozenset({"succeeded", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
}


def can_transition(current: str, nxt: str) -> bool:
    return nxt in _ALLOWED.get(current, frozenset())


def assert_transition(current: str, nxt: str) -> None:
    if not can_transition(current, nxt):
        raise ValueError(f"illegal transition {current} -> {nxt}")
