"""Orchestrator retry — model tier escalation (Task 62 P1)."""

from __future__ import annotations

from packages.model_registry import (
    ModelSpec,
    escalate_model_name,
    resolve_model_for_retry,
)


def test_escalate_model_name_moves_one_tier(monkeypatch) -> None:
    reg = {
        "cheap-m": ModelSpec(name="cheap-m", provider="p", tier="cheap", capability="chat"),
        "good-m": ModelSpec(name="good-m", provider="p", tier="good", capability="chat"),
        "best-m": ModelSpec(name="best-m", provider="p", tier="best", capability="chat"),
    }
    monkeypatch.setattr("packages.model_registry.get_registry", lambda: reg)
    monkeypatch.setattr(
        "packages.model_registry.get_model",
        lambda name: reg.get(name),
    )
    assert escalate_model_name("cheap-m") == "good-m"
    assert escalate_model_name("good-m") == "best-m"
    assert escalate_model_name("best-m") is None


def test_resolve_model_for_retry_attempt_one_unchanged(monkeypatch) -> None:
    reg = {
        "good-m": ModelSpec(name="good-m", provider="p", tier="good", capability="chat"),
        "best-m": ModelSpec(name="best-m", provider="p", tier="best", capability="chat"),
    }
    monkeypatch.setattr("packages.model_registry.get_registry", lambda: reg)
    monkeypatch.setattr(
        "packages.model_registry.get_model",
        lambda name: reg.get(name),
    )
    model, escalated = resolve_model_for_retry("good-m", 1)
    assert model == "good-m"
    assert escalated is None


def test_resolve_model_for_retry_attempt_two_escalates_or_same(monkeypatch) -> None:
    reg = {
        "good-m": ModelSpec(name="good-m", provider="p", tier="good", capability="chat"),
        "best-m": ModelSpec(name="best-m", provider="p", tier="best", capability="chat"),
    }
    monkeypatch.setattr("packages.model_registry.get_registry", lambda: reg)
    monkeypatch.setattr(
        "packages.model_registry.get_model",
        lambda name: reg.get(name),
    )
    model, escalated = resolve_model_for_retry("good-m", 2)
    assert model == "best-m"
    assert escalated == "best-m"

    model2, escalated2 = resolve_model_for_retry("best-m", 2)
    assert model2 == "best-m"
    assert escalated2 is None
