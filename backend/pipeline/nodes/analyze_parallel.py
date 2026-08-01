"""并行分析节点 — 意图 + 实体提取"""

from __future__ import annotations

import asyncio
import json
import os

from backend.observability.decorators import observe
from backend.pipeline.llm_helper import generate_text
from backend.pipeline.state import PipelineState


@observe(name="pipeline.analyze_parallel")
async def analyze_parallel(state: PipelineState) -> PipelineState:
    """并发分析意图和实体"""
    message = state["message"]

    from typing import Any, cast

    gathered = cast(
        tuple[Any],
        await asyncio.gather(
            _analyze_intent(message),
            return_exceptions=True,
        ),
    )
    intent_raw = gathered[0]
    intent_result: dict | BaseException = (
        intent_raw if isinstance(intent_raw, (dict, BaseException)) else {}
    )

    if isinstance(intent_result, dict):
        state["intent"] = intent_result.get("intent", "default")
        state["intent_confidence"] = float(intent_result.get("confidence", 0.0))
        state["entities"] = intent_result.get("entities", {}) or {}
    else:
        state["intent"] = "default"
        state["intent_confidence"] = 0.0
        state["entities"] = {}

    from backend.pipeline.cache.fingerprint_cache import make_fingerprint

    intent = state.get("intent") or "default"
    entities = state.get("entities") or {}
    state["fingerprint"] = make_fingerprint(intent, entities)

    return state


async def _analyze_intent(message: str) -> dict:
    mock = os.getenv("LLM_MOCK", "true").lower() == "true"
    if mock:
        greetings = ["你好", "嗨", "hello", "hi", "早上好", "晚上好"]
        advices = ["怎么办", "建议", "帮帮我", "有什么办法", "我该"]

        if any(g in message for g in greetings):
            return {"intent": "greeting", "confidence": 0.95, "entities": {}}
        if any(a in message for a in advices):
            return {
                "intent": "advice",
                "confidence": 0.85,
                "entities": {"topic": message},
            }
        return {"intent": "default", "confidence": 0.5, "entities": {}}

    prompt = (
        f"分析以下消息的意图(中文): {message}\n"
        f'输出 JSON: {{"intent": "advice|greeting|default", '
        f'"confidence": 0.0-1.0, "entities": {{}}}}'
    )
    response = await generate_text(prompt)
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"intent": "default", "confidence": 0.5, "entities": {}}
