"""Local intent BERT probe (not a separate process)."""

from __future__ import annotations

import importlib
from pathlib import Path


def test_intent_runtime_status_not_warmed(monkeypatch) -> None:
    mod = importlib.import_module("packages.intent.routers.intent_router")
    monkeypatch.setattr(mod, "_intent_service", None)
    st = mod.intent_runtime_status()
    assert st["status"] == "not_warmed"
    assert "path" in st
    assert "weights" in st


def test_probe_missing_weights(tmp_path: Path) -> None:
    from scripts.check_intent_model import _probe

    result = _probe(model_path=str(tmp_path / "empty"))
    assert result["bert_loaded"] is False
    assert result["backend"] == "rule_fallback"
    assert result["weights"] is False
