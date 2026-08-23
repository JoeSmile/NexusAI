"""Task 65 slice 1 — dataset quality helpers."""

from __future__ import annotations

from backend.modules.intent.dataset.quality import cohen_kappa, dual_label_kappa_report


def test_cohen_kappa_perfect() -> None:
    labels = ["a", "b", "a", "b"]
    assert cohen_kappa(labels, labels) == 1.0


def test_dual_label_kappa_report_pass() -> None:
    rows = [{"label_a": "greeting", "label_b": "greeting"} for _ in range(10)]
    report = dual_label_kappa_report(rows)
    assert report["pairs"] == 10
    assert report["passed"] is True
