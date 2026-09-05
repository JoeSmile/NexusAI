"""Task 85 — llm.generate capability + single-node workflow inputs."""

from __future__ import annotations

import pytest

from packages.auth.models import TenantContext
from packages.capability.builtin.register import register_builtin_tools
from packages.capability.errors import CapabilityNotFoundError
from packages.capability.registry import CapabilityRegistry
from packages.harness.base import HarnessResult
from packages.workflow.ir import (
    WorkflowIR,
    apply_workflow_input_defaults,
    validate_ir_capabilities,
)


@pytest.fixture
def tenant_user() -> TenantContext:
    return TenantContext(
        tenant_id="t-llm-gen",
        user_id="u1",
        role="user",
        extra_permissions=["chat:write"],
        is_cross_tenant=False,
    )


def test_llm_generate_registered_with_param_spec() -> None:
    reg = CapabilityRegistry()
    register_builtin_tools(reg)
    spec = reg.get("llm.generate")
    assert spec.permission == "chat:write"
    assert spec.spec.get("executor") == "builtin"
    assert spec.param_spec is not None
    assert spec.param_spec["instruction"]["required"] is True
    assert "user_material" in spec.param_spec


@pytest.mark.asyncio
async def test_llm_generate_handler_uses_harness(
    tenant_user: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.capability.builtin import handlers as h
    from packages.harness.llm import LLMHarness

    async def fake_generate(self, model, messages, tenant_id, **kwargs):
        assert tenant_id == "t-llm-gen"
        assert messages[0]["role"] == "user"
        body = messages[0]["content"]
        assert "写一段介绍" in body
        assert "中外合作办学" in body
        return HarnessResult(
            output="生成正文",
            success=True,
            metadata={"input_tokens": 3, "output_tokens": 5, "cost": 0.0},
        )

    monkeypatch.setattr(LLMHarness, "generate", fake_generate)
    result = await h.invoke_builtin_handler(
        "llm.generate",
        {"instruction": "写一段介绍", "user_material": "中外合作办学"},
        tenant_user,
    )
    assert result.get("ok") is True
    data = result.get("data") or {}
    assert data.get("text") == "生成正文"
    assert "model" in data
    assert (data.get("usage") or {}).get("output") == 5


@pytest.mark.asyncio
async def test_llm_generate_requires_instruction(
    tenant_user: TenantContext,
) -> None:
    from packages.capability.builtin.handlers import invoke_builtin_handler

    result = await invoke_builtin_handler("llm.generate", {}, tenant_user)
    assert result.get("ok") is False


def test_seed_ir_validates_against_llm_generate_param_spec() -> None:
    from packages.content_ops.workflow_seed import LLM_GENERATE_IR

    ir = WorkflowIR.model_validate(LLM_GENERATE_IR)
    assert ir.output_node_id == "gen"
    assert ir.edges == []
    assert ir.inputs["topic"].required is True
    assert ir.nodes[0].capability_id == "llm.generate"
    assert ir.nodes[0].params["instruction"] == "${input.instruction}"
    assert ir.nodes[0].params["user_material"] == "${input.topic}"

    reg = CapabilityRegistry()
    register_builtin_tools(reg)

    def exists(cid: str) -> bool:
        try:
            reg.get(cid)
            return True
        except CapabilityNotFoundError:
            return False

    def param_spec(cid: str) -> dict | None:
        try:
            spec = reg.get(cid)
        except CapabilityNotFoundError:
            return None
        return dict(spec.param_spec) if spec.param_spec else None

    validate_ir_capabilities(ir, get_param_spec=param_spec, capability_exists=exists)


def test_apply_workflow_input_defaults_fills_and_rejects() -> None:
    ir = WorkflowIR.model_validate(
        {
            "ir_schema": "1",
            "inputs": {
                "topic": {"name": "topic", "type": "string", "required": True},
                "instruction": {
                    "name": "instruction",
                    "type": "string",
                    "required": False,
                    "default": "默认指令",
                },
            },
            "nodes": [],
            "edges": [],
        }
    )
    filled = apply_workflow_input_defaults(ir, {"topic": "办学"})
    assert filled["topic"] == "办学"
    assert filled["instruction"] == "默认指令"
    with pytest.raises(ValueError, match="missing required"):
        apply_workflow_input_defaults(ir, {})
