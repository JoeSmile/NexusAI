"""Vision model helpers — registry, credentials, message blocks."""

from __future__ import annotations

import base64
import os

from packages.errors import ErrorCode, NexusAIException
from backend.core.model_registry import ModelSpec, get_model, get_registry


def select_vision_model_name(preferred: str | None = None) -> str:
    if preferred:
        spec = get_model(preferred)
        if spec is not None and spec.capability == "vision":
            return spec.name
    reg = get_registry()
    candidates = [
        s for s in reg.values() if s.enabled and s.capability == "vision"
    ]
    if not candidates:
        raise NexusAIException(
            ErrorCode.LLM_MODEL_NOT_ALLOWED.value,
            "vision_model_not_configured",
        )
    best = min(candidates, key=lambda s: (float(s.cost_per_1k), s.name))
    return best.name


def _api_key_from_spec(spec: ModelSpec) -> str:
    ref = (spec.api_key_ref or "").strip()
    if ref:
        val = os.getenv(ref, "").strip()
        if val:
            return val
    return (
        os.getenv("QWEN_API_KEY", "").strip()
        or os.getenv("LLM_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
    )


async def resolve_vision_credentials(
    tenant_id: str,
    model_name: str | None = None,
) -> tuple[str, str, str, str]:
    """Return (model, api_key, base_url, provider)."""
    name = select_vision_model_name(model_name)
    spec = get_model(name)
    if spec is None:
        raise NexusAIException(
            ErrorCode.LLM_MODEL_NOT_ALLOWED.value,
            "vision_model_not_configured",
        )

    try:
        from backend.core.llm_credentials import resolve_tenant_credential

        key = await resolve_tenant_credential(tenant_id, name)
        return name, key.api_key, key.base_url or spec.base_url, key.provider
    except NexusAIException:
        api_key = _api_key_from_spec(spec)
        if not api_key:
            raise NexusAIException(
                ErrorCode.LLM_KEY_MISSING.value,
                "vision_key_missing",
            ) from None
        return name, api_key, spec.base_url, spec.provider


def image_to_data_uri(content: bytes, content_type: str) -> str:
    mime = content_type if content_type.startswith("image/") else "image/jpeg"
    b64 = base64.standard_b64encode(content).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_vision_messages(text: str, image_data_uri: str) -> list[dict]:
    prompt = (text or "").strip() or "请描述这张图片的内容。"
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_uri}},
            ],
        }
    ]
