"""并行分析节点 — 情绪 + 意图 + 实体提取"""

from __future__ import annotations

import asyncio
import json
import os

from backend.observability.decorators import observe
from backend.pipeline.llm_helper import generate_text
from backend.pipeline.state import PipelineState


@observe(name="pipeline.analyze_parallel")
async def analyze_parallel(state: PipelineState) -> PipelineState:
    """并发分析情绪和意图"""
    message = state["message"]

    emotion_result, intent_result = await asyncio.gather(
        _analyze_emotion(message),
        _analyze_intent(message),
        return_exceptions=True,
    )

    if isinstance(emotion_result, dict):
        state["emotion"] = emotion_result.get("emotion", "neutral")
        state["emotion_intensity"] = float(emotion_result.get("intensity", 5.0))
    else:
        state["emotion"] = "neutral"
        state["emotion_intensity"] = 5.0

    if isinstance(intent_result, dict):
        state["intent"] = intent_result.get("intent", "default")
        state["intent_confidence"] = float(intent_result.get("confidence", 0.0))
        state["entities"] = intent_result.get("entities", {}) or {}
    else:
        state["intent"] = "default"
        state["intent_confidence"] = 0.0
        state["entities"] = {}

    from backend.pipeline.cache.fingerprint_cache import make_fingerprint

    if state.get("intent") and state.get("entities") is not None:
        state["fingerprint"] = make_fingerprint(
            state["intent"], state["entities"]
        )

    return state


async def _analyze_emotion(message: str) -> dict:
    mock = os.getenv("LLM_MOCK", "true").lower() == "true"
    if mock:
        emotions = {
            "焦虑": {"emotion": "焦虑", "intensity": 8},
            "伤心": {"emotion": "悲伤", "intensity": 7},
            "高兴": {"emotion": "高兴", "intensity": 6},
            "压力": {"emotion": "焦虑", "intensity": 8},
        }
        for keyword, result in emotions.items():
            if keyword in message:
                return result
        return {"emotion": "neutral", "intensity": 5.0}

    prompt = (
        f'分析以下消息的情绪(中文): {message}\n'
        f'输出 JSON: {{"emotion": "", "intensity": 0-10}}'
    )
    response = await generate_text(prompt)
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"emotion": "neutral", "intensity": 5.0}


async def _analyze_intent(message: str) -> dict:
    mock = os.getenv("LLM_MOCK", "true").lower() == "true"
    if mock:
        greetings = ["你好", "嗨", "hello", "hi", "早上好", "晚上好"]
        emotions = ["焦虑", "伤心", "害怕", "紧张", "压力", "孤独"]
        advices = ["怎么办", "建议", "帮帮我", "有什么办法", "我该"]

        if any(g in message for g in greetings):
            return {"intent": "greeting", "confidence": 0.95, "entities": {}}
        if any(e in message for e in emotions):
            return {
                "intent": "emotion",
                "confidence": 0.9,
                "entities": {"emotion": message},
            }
        if any(a in message for a in advices):
            return {
                "intent": "advice",
                "confidence": 0.85,
                "entities": {"topic": message},
            }
        return {"intent": "default", "confidence": 0.5, "entities": {}}

    prompt = (
        f"分析以下消息的意图(中文): {message}\n"
        f'输出 JSON: {{"intent": "emotion|advice|greeting|default", '
        f'"confidence": 0.0-1.0, "entities": {{}}}}'
    )
    response = await generate_text(prompt)
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"intent": "default", "confidence": 0.5, "entities": {}}
