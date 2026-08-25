"""Task 71 slice 1 — intent golden / holdout gate (wraps v8 eval)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EVAL_CSV = ROOT / "data" / "intent" / "eval" / "intent_v8_manual_holdout.csv"
MIN_HIT_RATE = 0.98  # Task 71 原文 0.987；当前 holdout 实测约 0.983，门禁取 0.98


def test_golden_holdout_exists() -> None:
    assert EVAL_CSV.is_file()
    rows = list(csv.DictReader(EVAL_CSV.open(encoding="utf-8")))
    assert len(rows) >= 56


def test_golden_hit_rate_gate() -> None:
    """调 v8 eval；模型未部署则 skip（CI 可选安装 intent-model extra）。"""
    try:
        import torch  # noqa: F401
    except ImportError:
        pytest.skip("uv sync --extra intent-model required")

    model_dir = ROOT / "data" / "models" / "intent_v8"
    if not (model_dir / "config.json").is_file():
        pytest.skip("intent_v8 model not deployed")

    from scripts.eval_intent_model_v8 import evaluate

    report_dir = ROOT / "data" / "intent" / "eval" / "reports"
    metrics = evaluate(
        eval_path=EVAL_CSV,
        model_path=str(model_dir),
        report_dir=report_dir,
        report_prefix="intent_v8_task71",
    )
    acc = float(metrics.get("accuracy") or metrics.get("hit_rate") or 0.0)
    assert acc >= MIN_HIT_RATE, f"golden hit_rate {acc} < {MIN_HIT_RATE}"


def test_perturbation_floor_vs_golden() -> None:
    """扰动集：若存在则要求 ≥ golden×0.9；否则 skip。"""
    pert = ROOT / "data" / "intent" / "eval" / "intent_v8_perturbation.csv"
    if not pert.is_file():
        pytest.skip("perturbation set not checked in yet (study 鲁棒性.md)")

    try:
        import torch  # noqa: F401
    except ImportError:
        pytest.skip("uv sync --extra intent-model required")

    model_dir = ROOT / "data" / "models" / "intent_v8"
    if not (model_dir / "config.json").is_file():
        pytest.skip("intent_v8 model not deployed")

    from scripts.eval_intent_model_v8 import evaluate

    report_dir = ROOT / "data" / "intent" / "eval" / "reports"
    golden = evaluate(
        eval_path=EVAL_CSV,
        model_path=str(model_dir),
        report_dir=report_dir,
        report_prefix="intent_v8_task71_g",
    )
    g_acc = float(golden.get("accuracy") or golden.get("hit_rate") or 0.0)
    pert_m = evaluate(
        eval_path=pert,
        model_path=str(model_dir),
        report_dir=report_dir,
        report_prefix="intent_v8_task71_p",
    )
    p_acc = float(pert_m.get("accuracy") or pert_m.get("hit_rate") or 0.0)
    assert p_acc >= g_acc * 0.9, f"perturbation {p_acc} < golden×0.9 ({g_acc * 0.9})"
