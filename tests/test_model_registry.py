"""ModelRegistry 路由策略测试（Task 22.02）"""

from __future__ import annotations

import backend.core.model_registry as registry
from backend.core.model_registry import ModelSpec, select_model_for_intent


def _set_registry(models: dict[str, ModelSpec]) -> None:
    registry._REGISTRY = models


def test_intent_tier_mapping():
    _set_registry(
        {
            "c": ModelSpec(name="c", provider="x", tier="cheap", cost_per_1k=0.1),
            "g": ModelSpec(name="g", provider="x", tier="good", cost_per_1k=0.2),
            "b": ModelSpec(name="b", provider="x", tier="best", cost_per_1k=0.3),
        }
    )
    assert select_model_for_intent("greeting").name == "c"
    assert select_model_for_intent("knowledge_query").name == "g"
    assert select_model_for_intent("unknown_intent").name == "b"


def test_cheapest_in_tier():
    _set_registry(
        {
            "pricey": ModelSpec(
                name="pricey", provider="x", tier="good", cost_per_1k=0.9
            ),
            "cheap": ModelSpec(
                name="cheap", provider="x", tier="good", cost_per_1k=0.1
            ),
        }
    )
    assert select_model_for_intent("knowledge_query").name == "cheap"


def test_disabled_models_skipped():
    _set_registry(
        {
            "off": ModelSpec(
                name="off",
                provider="x",
                tier="good",
                cost_per_1k=0.01,
                enabled=False,
            ),
            "on": ModelSpec(
                name="on", provider="x", tier="good", cost_per_1k=0.5, enabled=True
            ),
        }
    )
    assert select_model_for_intent("knowledge_query").name == "on"


def test_fallback_non_none():
    _set_registry({})
    spec = select_model_for_intent("greeting")
    assert spec is not None
    assert spec.name
