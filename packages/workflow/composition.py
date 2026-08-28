"""Composition depth budget (Wave 8 · R-H / R-I#3)."""

from __future__ import annotations

from dataclasses import dataclass

MAX_COMPOSITION_DEPTH = 3


@dataclass
class CompositionDepthExceeded(Exception):
    total: int
    run_depth: int
    agent_stack: int
    max_depth: int = MAX_COMPOSITION_DEPTH

    def __str__(self) -> str:
        return (
            f"composition_depth_exceeded total={self.total} "
            f"run={self.run_depth} agent={self.agent_stack} max={self.max_depth}"
        )


def check_composition_budget(run_depth: int, agent_stack: int) -> None:
    """Raise when nested run depth + agent layers exceed MAX_COMPOSITION_DEPTH."""
    total = int(run_depth) + int(agent_stack)
    if total > MAX_COMPOSITION_DEPTH:
        raise CompositionDepthExceeded(
            total=total,
            run_depth=int(run_depth),
            agent_stack=int(agent_stack),
            max_depth=MAX_COMPOSITION_DEPTH,
        )
