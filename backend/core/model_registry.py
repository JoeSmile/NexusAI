"""模型注册表 — 统一多模型路由（Task 21.01）"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelSpec:
    name: str
    provider: str
    base_url: str = ""
    api_key_ref: str = ""  # env var name or llm_api_keys alias
    capability: str = "chat"  # chat | embedding | vision
    cost_per_1k: float = 0.0005
    max_tokens: int = 1000
    enabled: bool = True
    tier: str = "good"  # cheap | good | best
    extra: dict[str, Any] = field(default_factory=dict)


_REGISTRY: dict[str, ModelSpec] | None = None


def _default_models() -> dict[str, ModelSpec]:
    cheap = os.getenv("MODEL_CHEAP", "deepseek-chat")
    good = os.getenv("MODEL_GOOD", "deepseek-chat")
    best = os.getenv("MODEL_BEST", "deepseek-chat")
    base = os.getenv("LLM_BASE_URL", "") or os.getenv("API_BASE_URL", "")
    models = {
        cheap: ModelSpec(
            name=cheap,
            provider="deepseek",
            base_url=base,
            api_key_ref="LLM_API_KEY",
            cost_per_1k=0.00014,
            max_tokens=100,
            tier="cheap",
        ),
        good: ModelSpec(
            name=good,
            provider="deepseek",
            base_url=base,
            api_key_ref="LLM_API_KEY",
            cost_per_1k=0.00014,
            max_tokens=500,
            tier="good",
        ),
        best: ModelSpec(
            name=best,
            provider="deepseek",
            base_url=base,
            api_key_ref="LLM_API_KEY",
            cost_per_1k=0.00014,
            max_tokens=1000,
            tier="best",
        ),
        "mock-local": ModelSpec(
            name="mock-local",
            provider="mock",
            base_url="http://localhost:8001/v1",
            api_key_ref="",
            cost_per_1k=0.0,
            max_tokens=500,
            tier="cheap",
            capability="chat",
        ),
    }
    # MODEL_REGISTRY_JSON='[{"name":"local-7b","provider":"vllm","base_url":"http://localhost:8001/v1",...}]'
    raw = os.getenv("MODEL_REGISTRY_JSON", "").strip()
    if not raw:
        try:
            from config import get_settings

            raw = (get_settings().model_registry_json or "").strip()
        except Exception:
            raw = ""
    if raw:
        try:
            for item in json.loads(raw):
                spec = ModelSpec(
                    name=str(item["name"]),
                    provider=str(item.get("provider", "openai")),
                    base_url=str(item.get("base_url", "")),
                    api_key_ref=str(item.get("api_key_ref", "LLM_API_KEY")),
                    capability=str(item.get("capability", "chat")),
                    cost_per_1k=float(item.get("cost_per_1k", 0.0005)),
                    max_tokens=int(item.get("max_tokens", 1000)),
                    enabled=bool(item.get("enabled", True)),
                    tier=str(item.get("tier", "good")),
                )
                models[spec.name] = spec
        except Exception:
            pass
    return models


def get_registry() -> dict[str, ModelSpec]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _default_models()
    return _REGISTRY


def reload_registry() -> dict[str, ModelSpec]:
    global _REGISTRY
    _REGISTRY = _default_models()
    return _REGISTRY


def get_model(name: str) -> ModelSpec | None:
    reg = get_registry()
    spec = reg.get(name)
    if spec and spec.enabled:
        return spec
    return None


def select_model_for_intent(intent: str) -> ModelSpec:
    """按意图档位选择模型：greeting→cheap, knowledge_query/advice→good, else→best。"""
    reg = get_registry()
    tier_map = {
        "greeting": "cheap",
        "chat": "cheap",
        "knowledge_query": "good",
        "advice": "good",
        "function": "good",
    }
    tier = tier_map.get(intent or "default", "best")
    for spec in reg.values():
        if spec.enabled and spec.capability == "chat" and spec.tier == tier:
            return spec
    # fallback: any enabled chat model
    for spec in reg.values():
        if spec.enabled and spec.capability == "chat":
            return spec
    return ModelSpec(name=os.getenv("MODEL_BEST", "deepseek-chat"), provider="default")


def list_models() -> list[ModelSpec]:
    return [m for m in get_registry().values() if m.enabled]
