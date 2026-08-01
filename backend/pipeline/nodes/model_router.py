"""模型路由节点 — 双路径 + ModelRegistry + Skill 二级权限"""

from __future__ import annotations

from backend.core.cost_manager import estimate_cost
from backend.core.model_registry import get_model, select_model_for_intent
from backend.observability.decorators import enrich_span, observe
from backend.observability.sampling import set_tracing_enabled, should_sample
from backend.pipeline.state import PipelineState
from backend.skills.registry import registry


def _maybe_disable_short_path_trace(finish_reason: str) -> None:
    """短路径按配置降采样：未命中则关闭后续 span。"""
    if not should_sample(finish_reason):
        set_tracing_enabled(False)


@observe(name="pipeline.model_router")
async def model_router(state: PipelineState) -> PipelineState:
    """双路径路由: Skill 短路径 / LLM 长路径（模型来自 ModelRegistry）"""
    intent = state.get("intent", "default") or "default"
    confidence = float(state.get("intent_confidence", 0.0) or 0.0)

    if confidence >= 0.85:
        try:
            skill = registry.get_skill_for_intent(intent, confidence)
            if skill:
                result = await registry.execute_skill(
                    skill_id=skill.id,
                    entities=state.get("entities") or {},
                    tenant_id=state["tenant_id"],
                    user_context=state.get("user_context") or {},
                )
                state["response"] = result.output
                state["finish_reason"] = (
                    "skill_executed" if result.success else (result.error or "error")
                )
                state["total_cost"] = 0.0
                state["pipeline_latency_ms"] = result.latency_ms
                if result.error == "PENDING_APPROVAL":
                    state["approval_request_id"] = result.approval_request_id
                if result.error:
                    state["error_code"] = result.error
                enrich_span(
                    metadata={
                        "path": "short",
                        "intent": intent,
                        "skill_id": skill.id,
                    },
                    output_data=state.get("finish_reason"),
                )
                _maybe_disable_short_path_trace(state["finish_reason"])
                return state
        except Exception as e:
            state["response"] = f"Skill 执行错误: {e!s}"
            state["finish_reason"] = "error"
            state["error_code"] = "SKILL_001"
            return state

    # A/B 变体可覆盖模型名
    override = (state.get("ab_variant_config") or {}).get("model")
    if override:
        spec = get_model(str(override)) or select_model_for_intent(intent)
    else:
        spec = select_model_for_intent(intent)

    state["selected_model"] = spec.name
    state["estimated_cost"] = estimate_cost(spec.name, spec.max_tokens)
    state["finish_reason"] = "routed_to_llm"

    if spec.base_url:
        state["llm_base_url"] = spec.base_url

    # 注入租户级 LLM API Key（DB 加密 → 运行时解密；无则走 env fallback）
    try:
        from backend.core.key_repository import LLMKeyRepository

        key_data = await LLMKeyRepository().get_key(state["tenant_id"], spec.provider)
        if key_data:
            state["llm_api_key"] = key_data.api_key
            state["llm_base_url"] = key_data.base_url or spec.base_url or state.get(
                "llm_base_url"
            )
            state["llm_key_id"] = key_data.id
            state["llm_key_version"] = key_data.key_version
        elif spec.api_key_ref:
            import os

            env_key = os.getenv(spec.api_key_ref, "")
            if env_key:
                state["llm_api_key"] = env_key
    except Exception:
        pass

    return state


def route_short_or_long(state: PipelineState) -> str:
    """条件边: 仅「非流式的长路径」去 llm_generate；其余(短路径/错误/流式)一律 conversion_hook。

    反向判断而非枚举终止态: skill 失败(finish_reason=error / 任意错误字符串)已有响应,
    必须终止并记转化,不能遗漏式落进 LLM 被覆盖(曾致错误被吞 + 双份成本 + 审计不一致)。
    """
    if state.get("finish_reason") == "routed_to_llm" and not state.get("stream_mode"):
        return "llm_generate"
    return "conversion_hook"
