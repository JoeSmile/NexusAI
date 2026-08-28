"""Task 65 slice 9 — v8 model accuracy on hand-written holdout (data/intent/eval/)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EVAL_CSV = ROOT / "data" / "intent" / "eval" / "intent_v8_manual_holdout.csv"
LATEST_REPORT = ROOT / "data" / "intent" / "eval" / "reports" / "intent_v8_eval_latest.json"

# Manual holdout gate — below this fails CI when model is deployed
MIN_ACCURACY = 0.90
MIN_MACRO_F1 = 0.88


def test_holdout_dataset_exists_and_balanced() -> None:
    assert EVAL_CSV.is_file(), "missing hand-written eval CSV"
    rows = list(csv.DictReader(EVAL_CSV.open(encoding="utf-8")))
    assert len(rows) >= 56, "expect ≥7 samples × 8 classes"
    labels = {r["label"] for r in rows}
    assert labels == {
        "greeting",
        "pre_sales",
        "after_sales",
        "content_creation",
        "content_analysis",
        "knowledge_query",
        "function",
        "conversation",
    }


def test_v8_accuracy_on_manual_holdout() -> None:
    from scripts.eval_intent_model_v8 import evaluate

    try:
        import torch  # noqa: F401
    except ImportError:
        pytest.skip("uv sync --extra intent-model required")

    from packages.intent.core.intent_classifier import MLIntentClassifier

    model_dir = ROOT / "data" / "models" / "intent_v8"
    if not (model_dir / "config.json").is_file():
        pytest.skip("model not deployed — run scripts/copy_intent_model.py")

    clf = MLIntentClassifier(model_path=str(model_dir))
    if not clf.is_loaded:
        pytest.skip("model failed to load")

    report = evaluate(
        eval_path=EVAL_CSV,
        model_path=str(model_dir),
        report_dir=ROOT / "data" / "intent" / "eval" / "reports",
    )
    assert report["accuracy"] >= MIN_ACCURACY, report["misclassified"]
    assert report["macro_f1"] >= MIN_MACRO_F1
    assert LATEST_REPORT.is_file()
    saved = json.loads(LATEST_REPORT.read_text(encoding="utf-8"))
    assert saved["total"] == report["total"]
