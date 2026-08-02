"""统一 LLM 客户端工厂 — 复用 provider mock/record/replay（EVID-08 / Task 26）

RAG / Agent / Eval 等旁路通过 get_llm_client() 获取客户端，与 /chat 的
LLM_PROVIDER 行为一致；不再各自直读 LLM_API_KEY。
"""

from __future__ import annotations

import os
from typing import Any

from backend.core.harness.provider import (
    get_llm_provider,
    load_fixture,
    mock_response,
    save_fixture,
)
from backend.modules.llm.harness import resolve_llm_settings


def _messages_to_prompt(messages: list[dict]) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages)


def _normalize_messages(input_: Any, *, system: str | None = None) -> list[dict]:
    """将 invoke 入参 / Agent messages 统一为 OpenAI-style messages。"""
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})

    if isinstance(input_, str):
        messages.append({"role": "user", "content": input_})
        return messages

    if isinstance(input_, list):
        for item in input_:
            if isinstance(item, dict):
                role = item.get("role") or "user"
                content = item.get("content", "")
                messages.append({"role": role, "content": str(content)})
            else:
                content = getattr(item, "content", str(item))
                msg_type = getattr(item, "type", None) or getattr(item, "role", "user")
                if msg_type in ("ai", "assistant"):
                    role = "assistant"
                elif msg_type == "system":
                    role = "system"
                else:
                    role = "user"
                messages.append({"role": role, "content": str(content)})
        return messages

    to_string = getattr(input_, "to_string", None)
    if callable(to_string):
        messages.append({"role": "user", "content": to_string()})
    else:
        messages.append({"role": "user", "content": str(input_)})
    return messages


def _mock_or_eval_json(model: str, prompt: str) -> str:
    """评估提示词返回可解析 JSON，其余走普通 mock 文本。"""
    if "accuracy_score" in prompt and "safety_score" in prompt:
        return (
            '{"accuracy_score": 4, "naturalness_score": 4, "safety_score": 5, '
            '"accuracy_reasoning": "mock", "naturalness_reasoning": "mock", '
            '"safety_reasoning": "mock", "overall_comment": "mock offline eval", '
            '"strengths": ["deterministic"], "weaknesses": [], '
            '"improvement_suggestions": []}'
        )
    return mock_response(model, prompt)


def _load_key_chain_sync(
    tenant_id: str, key_provider: str, limit: int = 3
) -> list:
    """尽力同步拉取候选链;失败则返回空(由调用方回退 env)。"""
    import asyncio

    from backend.core.key_repository import LLMKeyRepository

    async def _load():
        return await LLMKeyRepository().get_key_chain(
            tenant_id, key_provider, limit=limit
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(_load())
        except Exception:
            return []
    return []


def complete_via_provider(
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.7,
    api_key: str | None = None,
    base_url: str | None = None,
    tenant_id: str = "default",
    key_provider: str = "default",
    key_chain: list | None = None,
) -> str:
    """按 LLM_PROVIDER 完成一次文本生成（同步）。openai/record 支持 429/401 切 key。"""
    provider = get_llm_provider()
    prompt = _messages_to_prompt(messages)

    if provider == "mock":
        return _mock_or_eval_json(model, prompt)

    if provider == "replay":
        hit = load_fixture(model, messages)
        if hit is not None:
            return hit
        return _mock_or_eval_json(model, prompt)

    from openai import OpenAI

    from backend.core.key_failover import call_with_key_failover_sync
    from backend.core.key_repository import LLMKey

    keys = list(key_chain) if key_chain else _load_key_chain_sync(tenant_id, key_provider)
    if not keys:
        key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        if not key:
            raise RuntimeError(
                f"LLM_PROVIDER={provider} 需要配置 LLM_API_KEY（或 OPENAI_API_KEY）；"
                "离线演示请使用 LLM_PROVIDER=mock 或 LLM_PROVIDER=replay"
            )
        keys = [
            LLMKey(
                id="fallback",
                tenant_id=tenant_id,
                provider=key_provider,
                base_url=base_url or os.getenv("LLM_BASE_URL") or "",
                api_key=key,
                key_version=0,
                is_active=True,
                expires_at=None,
            )
        ]

    def _call(plain_key: str, url: str) -> str:
        client = OpenAI(
            api_key=plain_key,
            base_url=url or base_url or os.getenv("LLM_BASE_URL") or None,
        )
        resp = client.chat.completions.create(
            model=model or "default",
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
        )
        text = (resp.choices[0].message.content or "").strip()
        if provider == "record" and text:
            save_fixture(model, messages, text)
        return text

    return call_with_key_failover_sync(
        keys,
        _call,
        tenant_id=tenant_id,
        provider=key_provider,
    )


def _build_langchain_chat_model(
    model: str,
    *,
    temperature: float,
    api_key: str | None,
    base_url: str | None,
) -> Any:
    """构造兼容 LangChain BaseChatModel 的客户端（invoke/predict + complete_chat）。"""
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, BaseMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from pydantic import Field

    class HarnessChatModel(BaseChatModel):
        """Provider-aware ChatModel — RAG / Eval LangChain 链可用。"""

        model_name: str = Field(default="default")
        temperature: float = 0.7
        openai_api_key: str | None = None
        openai_api_base: str | None = None

        @property
        def _llm_type(self) -> str:
            return "harness"

        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> ChatResult:
            normalized = _normalize_messages(messages)
            text = complete_via_provider(
                self.model_name,
                normalized,
                temperature=self.temperature,
                api_key=self.openai_api_key,
                base_url=self.openai_api_base,
            )
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content=text))]
            )

        def complete_chat(
            self, messages: list[dict], system: str | None = None
        ) -> str:
            """Agent 适配入口：OpenAI-style messages → 纯文本（不与 LC.agenerate 冲突）。"""
            return complete_via_provider(
                self.model_name,
                _normalize_messages(messages, system=system),
                temperature=self.temperature,
                api_key=self.openai_api_key,
                base_url=self.openai_api_base,
            )

        async def acomplete_chat(
            self, messages: list[dict], system: str | None = None
        ) -> str:
            return self.complete_chat(messages, system=system)

    return HarnessChatModel(
        model_name=model,
        temperature=temperature,
        openai_api_key=api_key,
        openai_api_base=base_url,
    )


class _FallbackLLMClient:
    """LangChain 不可用时的最小客户端。"""

    def __init__(
        self,
        model: str,
        *,
        temperature: float = 0.7,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self.model_name = model
        self.temperature = temperature
        self._api_key = api_key
        self._base_url = base_url

    def invoke(self, input_: Any, config: Any = None, **kwargs: Any) -> Any:
        text = complete_via_provider(
            self.model_name,
            _normalize_messages(input_),
            temperature=self.temperature,
            api_key=self._api_key,
            base_url=self._base_url,
        )
        return type("Msg", (), {"content": text})()

    def predict(self, text: str, **kwargs: Any) -> str:
        return self.invoke(text).content

    def complete_chat(self, messages: list[dict], system: str | None = None) -> str:
        return complete_via_provider(
            self.model_name,
            _normalize_messages(messages, system=system),
            temperature=self.temperature,
            api_key=self._api_key,
            base_url=self._base_url,
        )

    async def acomplete_chat(
        self, messages: list[dict], system: str | None = None
    ) -> str:
        return self.complete_chat(messages, system=system)

    # Agent 旧探测名（无 LangChain 时不会冲突）
    async def agenerate(self, messages: list[dict], system: str | None = None) -> str:
        return self.complete_chat(messages, system=system)

    def generate(self, messages: list[dict], system: str | None = None) -> str:
        return self.complete_chat(messages, system=system)


def get_llm_client(
    *,
    temperature: float = 0.7,
    model: str | None = None,
    prefer_evaluation_model: bool = False,
    **_extra: Any,
) -> Any:
    """
    按 LLM_PROVIDER 返回统一 LLM 客户端。

    - mock / replay（及无密钥）: 走 harness provider，不依赖 LLM_API_KEY
    - record / openai: 真实调用；record 时落盘 fixture
    """
    settings = resolve_llm_settings(
        model=model, prefer_evaluation_model=prefer_evaluation_model
    )
    resolved_model = settings.model or "default"

    try:
        return _build_langchain_chat_model(
            resolved_model,
            temperature=temperature,
            api_key=settings.api_key,
            base_url=settings.base_url,
        )
    except ImportError:
        return _FallbackLLMClient(
            resolved_model,
            temperature=temperature,
            api_key=settings.api_key,
            base_url=settings.base_url,
        )
