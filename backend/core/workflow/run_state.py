"""Run status machine (Wave D1 + E2 suspended/cancelled/waiting)."""

from __future__ import annotations

from typing import Literal

RunStatus = Literal[
    "pending", "running", "succeeded", "failed", "suspended", "cancelled"
]
NodeStatus = Literal["pending", "running", "succeeded", "failed", "waiting"]

_ALLOWED: dict[str, frozenset[str]] = {
    # failed: 并发超限/预检失败直接终态(execute_run 429 路径)
    "pending": frozenset({"running", "failed", "cancelled"}),
    "running": frozenset({"succeeded", "failed", "suspended", "cancelled"}),
    "suspended": frozenset({"running", "failed", "cancelled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

_NODE_ALLOWED: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "failed", "waiting"}),
    "running": frozenset({"succeeded", "failed", "waiting"}),
    "waiting": frozenset({"running", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
}


def can_transition(current: str, nxt: str) -> bool:
    return nxt in _ALLOWED.get(current, frozenset())


def assert_transition(current: str, nxt: str) -> None:
    if not can_transition(current, nxt):
        raise ValueError(f"illegal transition {current} -> {nxt}")


def can_node_transition(current: str, nxt: str) -> bool:
    return nxt in _NODE_ALLOWED.get(current, frozenset())


def assert_node_transition(current: str, nxt: str) -> None:
    if not can_node_transition(current, nxt):
        raise ValueError(f"illegal node transition {current} -> {nxt}")
