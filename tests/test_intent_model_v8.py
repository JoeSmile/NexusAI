"""Task 65 slice 9 — v8 BERT intent model load + tier routing + fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.intent.core.intent_classifier import (
    MLIntentClassifier,
    resolve_intent_model_path,
)
from packages.intent.models.intent_models import IntentType, confidence_tier

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_V8 = ROOT / "data" / "models" / "intent_v8"
INTENT_PROJECT_V8 = Path(r"D:\LLMs\intent_project\models\intent_model_v8\model")

V8_SAMPLES: list[tuple[str, IntentType]] = [
    ("你好呀", IntentType.GREETING),
    ("早上好", IntentType.GREETING),
    ("你们产品多少钱", IntentType.PRE_SALES),
    ("能对比一下和友商的方案吗", IntentType.PRE_SALES),
    ("发票怎么开", IntentType.AFTER_SALES),
    ("我要投诉", IntentType.AFTER_SALES),
    ("帮我写个口播稿", IntentType.CONTENT_CREATION),
    ("生成一篇社媒文案", IntentType.CONTENT_CREATION),
    ("分析一下竞品", IntentType.CONTENT_ANALYSIS),
    ("热点挖掘一下", IntentType.CONTENT_ANALYSIS),
    ("考勤制度是什么", IntentType.KNOWLEDGE_QUERY),
    ("合规要求有哪些", IntentType.KNOWLEDGE_QUERY),
    ("提醒我明天开会", IntentType.FUNCTION),
    ("帮我设个闹钟", IntentType.FUNCTION),
    ("今天天气不错", IntentType.CONVERSATION),
    ("随便聊聊", IntentType.CONVERSATION),
]


def _model_dir() -> Path | None:
    for candidate in (DEFAULT_V8, INTENT_PROJECT_V8):
        if (candidate / "config.json").is_file():
            return candidate
    return None


def test_confidence_tier_bands() -> None:
    assert confidence_tier(0.90) == "high"
    assert confidence_tier(0.85) == "high"
    assert confidence_tier(0.70) == "low"
    assert confidence_tier(0.40) == "low"
    assert confidence_tier(0.39) == "fallback"


def test_missing_model_path_falls_back_without_error(tmp_path: Path) -> None:
    clf = MLIntentClassifier(model_path=str(tmp_path / "missing"))
    assert clf.is_loaded is False
    result = clf.classify("怎么退款")
    assert result.intent == IntentType.AFTER_SALES
    assert result.source == "rule"
    assert result.tier in {"high", "low", "fallback"}


def test_resolve_intent_model_path_relative() -> None:
    path = resolve_intent_model_path("data/models/intent_v8")
    assert path.name == "intent_v8"
    assert "data" in path.parts


@pytest.mark.parametrize(("text", "expected"), V8_SAMPLES)
def test_v8_model_predicts_eight_classes(text: str, expected: IntentType) -> None:
    model_dir = _model_dir()
    if model_dir is None:
        pytest.skip("v8 model not deployed (run scripts/copy_intent_model.py)")
    try:
        import torch  # noqa: F401
        from transformers import AutoModelForSequenceClassification  # noqa: F401
    except ImportError:
        pytest.skip("uv sync --extra intent-model required")

    clf = MLIntentClassifier(model_path=str(model_dir))
    assert clf.is_loaded is True
    result = clf.classify(text)
    assert result.intent == expected, f"{text!r} -> {result.intent} (conf={result.confidence:.3f})"
    assert result.source == "model"
    assert result.tier in {"high", "low", "fallback"}
    assert result.confidence >= 0.0


def test_v8_model_high_confidence_on_clear_queries() -> None:
    model_dir = _model_dir()
    if model_dir is None:
        pytest.skip("v8 model not deployed")
    try:
        import torch  # noqa: F401
    except ImportError:
        pytest.skip("uv sync --extra intent-model required")

    clf = MLIntentClassifier(model_path=str(model_dir))
    if not clf.is_loaded:
        pytest.skip("model failed to load")
    for text in ("你们产品多少钱", "发票怎么开", "帮我写个口播稿"):
        result = clf.classify(text)
        assert result.tier == "high", f"{text!r} tier={result.tier} conf={result.confidence}"
