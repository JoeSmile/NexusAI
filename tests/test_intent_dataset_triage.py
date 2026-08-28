"""Task 65 slice 1 — intent dataset triage."""

from __future__ import annotations

from packages.intent.dataset.triage import (
    RULE_WEAK_THRESHOLD,
    triage_query,
    triage_samples,
)


def test_triage_greeting_weak_label() -> None:
    result = triage_query("你好呀")
    assert result["bucket"] == "weak_label"
    assert result["label"] == "greeting"
    assert result["confidence"] >= RULE_WEAK_THRESHOLD


def test_triage_samples_dedupes() -> None:
    buckets = triage_samples(["你好", "你好", ""])
    assert len(buckets["weak_label"]) == 1
    assert buckets["skip"] == []
