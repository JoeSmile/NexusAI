"""LLM helpers for pipeline nodes — soft mock when mock provider or no key."""

from __future__ import annotations

import os


async def generate_text(prompt: str, model: str = "", api_key: str = "", base_url: str = "") -> str:
    from packages.harness.provider import get_llm_provider, mock_response

    provider = get_llm_provider()
    key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""

    # mock 或无 key 时一律软 mock,不真调外部
    if provider == "mock" or (provider == "openai" and not key):
        return mock_response(model, prompt)

    # openai:真实调用
    result = "系统暂时繁忙，请稍后再试。"
    try:
        from packages.llm.core.llm_core import ChatEngine

        engine = ChatEngine()
        # ChatEngine.chat is sync request-shaped; fall back to requests via engine internals
        if hasattr(engine, "chat"):
            from packages.models import ChatRequest

            resp = engine.chat(ChatRequest(message=prompt, session_id="pipeline", user_id="pipeline"))
            content = getattr(resp, "response", None) or getattr(resp, "message", None) or str(resp)
            result = str(content)
    except Exception as exc:
        result = f"系统暂时繁忙，请稍后再试。({exc})"

    return result
