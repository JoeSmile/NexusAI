"""并行分析节点 — 意图 + 实体提取"""

from __future__ import annotations

import asyncio

from backend.observability.decorators import observe
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
    """意图分析 — 与 /intent/detect 同源(规则+模型混合,离线可用)。

    修复(EVID-16): 旧实现是 LLM_MOCK 玩具启发式(只认 greeting/advice,其余全
    default/0.5),导致管线内所有请求路由到 best 档,三档路由从未生效。
    异常时降级保守默认(best 档),不阻断管线。
    """
    try:
        from backend.modules.intent.routers.intent_router import get_intent_service

        result = get_intent_service().intent_classifier.detect_intent(message)
        raw = result.intent
        intent = raw.value if hasattr(raw, "value") else str(raw)
        return {
            "intent": intent,
            "confidence": float(result.confidence),
            "entities": {},
        }
    except Exception:
        return {"intent": "default", "confidence": 0.5, "entities": {}}
