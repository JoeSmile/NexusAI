"""LLM helpers for pipeline nodes — soft mock when LLM_MOCK or no key."""

from __future__ import annotations

import os


async def generate_text(prompt: str, model: str = "", api_key: str = "", base_url: str = "") -> str:
    from backend.core.harness.provider import (
        get_llm_provider,
        load_fixture,
        mock_response,
        save_fixture,
    )

    provider = get_llm_provider()
    key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""

    if provider == "mock" or (provider in ("replay", "openai", "record") and not key):
        return mock_response(model, prompt)
    if provider == "replay":
        hit = load_fixture(model, [{"role": "user", "content": prompt}])
        if hit is not None:
            return hit
        return mock_response(model, prompt)

    # record / openai:真实调用(record 落盘 fixture)
    result = "系统暂时繁忙，请稍后再试。"
    try:
        from backend.modules.llm.core.llm_core import ChatEngine

        engine = ChatEngine()
        # ChatEngine.chat is sync request-shaped; fall back to requests via engine internals
        if hasattr(engine, "chat"):
            from backend.models import ChatRequest

            resp = engine.chat(ChatRequest(message=prompt, session_id="pipeline", user_id="pipeline"))
            content = getattr(resp, "response", None) or getattr(resp, "message", None) or str(resp)
            result = str(content)
    except Exception as exc:
        result = f"系统暂时繁忙，请稍后再试。({exc})"

    if provider == "record":
        save_fixture(model, [{"role": "user", "content": prompt}], result)
    return result
