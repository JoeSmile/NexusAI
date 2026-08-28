"""Dual-mode retrieval switch (Task 61 slice 4)."""

from __future__ import annotations

from packages.plan.retrieval_mode import choose_retrieval_mode


def test_mode_a_for_small_catalog() -> None:
    assert choose_retrieval_mode(candidate_count=2, cold_items=[]) == "A"


def test_mode_b_for_large_catalog() -> None:
    assert choose_retrieval_mode(candidate_count=8, cold_items=[]) == "B"


def test_mode_b_for_long_cold_doc() -> None:
    assert (
        choose_retrieval_mode(
            candidate_count=4,
            cold_items=[{"summary": "x" * 600}],
        )
        == "B"
    )
