"""模型路由节点 — 双路径 + ModelRegistry + Skill 二级权限"""

from __future__ import annotations

from packages.cost_manager import estimate_cost
from packages.errors import NexusAIException
from backend.core.llm_credentials import resolve_tenant_credential
from packages.model_registry import get_model, select_model_for_intent
from backend.observability.decorators import enrich_span, observe
from backend.observability.sampling import set_tracing_enabled, should_sample
from packages.skills.registry import registry
from packages.pipeline.intent_path import resolve_short_path_skill, skill_to_state
from packages.pipeline.state import PipelineState


def _maybe_disable_short_path_trace(finish_reason: str) -> None:
    """短路径按配置降采样：未命中则关闭后续 span。"""
    if not should_sample(finish_reason):
        set_tracing_enabled(False)


@observe(name="pipeline.model_router")
async def model_router(state: PipelineState) -> PipelineState:
    """双路径路由: Skill 短路径 / LLM 长路径（模型来自 ModelRegistry）"""
    if state.get("triggered_run") or state.get("finish_reason") == "workflow_triggered":
        enrich_span(metadata={"path": "workflow_bridge"})
        return state

    intent = state.get("intent", "default") or "default"
    confidence = float(state.get("intent_confidence", 0.0) or 0.0)

    # Task 43: 复用 task_plan 预解析的 short_path_skill（同源 helper）
    skill = resolve_short_path_skill(state)
    state["short_path_skill"] = skill_to_state(skill)

    if confidence >= 0.85 and skill is not None:
        try:
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
            # G7：短路径跳过 guardrails_output → 此处强制脱敏
            try:
                from packages.pipeline.nodes.guardrails_output import (
                    apply_student_output_redaction,
                )

                apply_student_output_redaction(state)
            except Exception:
                # I-7(评审 08-15)：禁静默 pass——脱敏失败可观测
                import logging

                logging.getLogger(__name__).exception(
                    "short-path student redaction failed"
                )
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

    # A/B 或用户显式选择可覆盖模型名
    preferred = (state.get("preferred_model") or "").strip()
    if not preferred:
        from backend.core.llm_credentials import resolve_chat_model_for_request

        try:
            preferred = await resolve_chat_model_for_request(state["tenant_id"], None)
            state["preferred_model"] = preferred
        except NexusAIException as e:
            state["finish_reason"] = "error"
            state["error_code"] = e.code or "LLM_KEY_001"
            state["response"] = "请在设置中配置公司 Key 后再发起对话"
            return state
    override = preferred or (state.get("ab_variant_config") or {}).get("model")
    if override:
        spec = get_model(str(override)) or select_model_for_intent(intent)
    else:
        spec = select_model_for_intent(intent)

    preferred = (state.get("preferred_model") or "").strip() or spec.name
    state["selected_model"] = preferred
    state["estimated_cost"] = estimate_cost(preferred, spec.max_tokens)

    from packages.pipeline.cache.semantic_cache import try_apply_semantic_cache

    if try_apply_semantic_cache(state):
        enrich_span(
            metadata={"path": "semantic_cache", "intent": intent, "model": preferred},
            output_data=state.get("finish_reason"),
        )
        _maybe_disable_short_path_trace(state["finish_reason"])
        return state

    state["finish_reason"] = "routed_to_llm"
    state["llm_key_provider"] = spec.provider or "default"

    if spec.base_url:
        state["llm_base_url"] = spec.base_url

    try:
        key_data = await resolve_tenant_credential(state["tenant_id"], preferred)
    except NexusAIException as e:
        state["finish_reason"] = "error"
        state["error_code"] = e.code or "LLM_KEY_001"
        state["response"] = "请在设置中配置公司 Key 后再发起对话"
        return state
    except Exception:
        state["finish_reason"] = "error"
        state["error_code"] = "LLM_KEY_001"
        state["response"] = "请在设置中配置公司 Key 后再发起对话"
        return state

    state["llm_api_key"] = key_data.api_key
    state["llm_base_url"] = (
        key_data.base_url or spec.base_url or state.get("llm_base_url") or ""
    )
    state["llm_key_id"] = key_data.id
    state["llm_key_version"] = key_data.key_version

    from packages.billing.context import bind_billing_from_pipeline_state

    bind_billing_from_pipeline_state(state)

    return state


def route_short_or_long(state: PipelineState) -> str:
    """条件边: 仅「非流式的长路径」去 llm_generate。

    反向判断而非枚举终止态: skill 失败(finish_reason=error / 任意错误字符串)已有响应,
    必须终止并落库,不能遗漏式落进 LLM 被覆盖(曾致错误被吞 + 双份成本 + 审计不一致)。

    流式长路径(routed_to_llm + stream_mode)仍走 conversion_hook：token 在路由层生成,
    write_memory 由 SSE 结束后补跑，避免图内先写入空回复。
    """
    if state.get("finish_reason") == "routed_to_llm" and not state.get("stream_mode"):
        return "llm_generate"
    if state.get("finish_reason") == "routed_to_llm" and state.get("stream_mode"):
        return "conversion_hook"
    return "write_memory"
