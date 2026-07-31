"""LLM helpers for pipeline nodes — soft mock when LLM_MOCK or no key."""

from __future__ import annotations

import os


async def generate_text(prompt: str, model: str = "", api_key: str = "", base_url: str = "") -> str:
    mock = os.getenv("LLM_MOCK", "true").lower() == "true"
    key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    if mock or not key:
        snippet = prompt.strip().replace("\n", " ")[-180:]
        return f"[mock:{model or 'default'}] 已收到：{snippet}"

    try:
        from backend.modules.llm.core.llm_core import ChatEngine

        engine = ChatEngine()
        # ChatEngine.chat is sync request-shaped; fall back to requests via engine internals
        if hasattr(engine, "chat"):
            from backend.models import ChatRequest

            resp = engine.chat(ChatRequest(message=prompt, session_id="pipeline", user_id="pipeline"))
            content = getattr(resp, "response", None) or getattr(resp, "message", None) or str(resp)
            return str(content)
    except Exception as exc:
        return f"系统暂时繁忙，请稍后再试。({exc})"

    return "系统暂时繁忙，请稍后再试。"
